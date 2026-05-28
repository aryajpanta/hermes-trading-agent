/**
 * Trade Reviewer
 * Reviews trade performance, compares against goals, and generates improvement suggestions.
 * Designed to be run by Hermes Agent on a weekly cadence.
 */
import store from '../data/store.js';
import * as perf from '../analytics/performance.js';
import * as scorer from '../analytics/scorer.js';
import getConfig from '../config/index.js';

const config = getConfig();

/**
 * Full review cycle — analyzes trades, scores them, generates report.
 * Returns a structured review that Hermes can use for self-improvement.
 */
export async function runReview() {
  const trades = store.read('trades') || [];
  const portfolio = store.read('portfolio');
  const strategyConfig = config.strategy;
  const goals = strategyConfig.goals || {};
  const previousReview = store.read('reviews/latest');

  // Calculate performance metrics
  const performance = perf.calcPerformance(trades, portfolio);

  // Score all trades
  const tradeScores = scorer.scoreAllTrades(trades, goals);

  // Generate performance report text
  const reportText = perf.generateReport(performance, goals);

  // Analyze patterns
  const patterns = analyzePatterns(trades, performance);

  // Generate improvement hypotheses
  const hypotheses = generateHypotheses(performance, tradeScores, patterns, previousReview);

  // Determine action items
  const actions = determineActions(performance, goals, hypotheses);

  const review = {
    timestamp: new Date().toISOString(),
    cycle: (previousReview?.cycle || 0) + 1,
    performance,
    tradeScores,
    patterns,
    hypotheses,
    actions,
    reportText,
  };

  // Save review
  store.write('reviews/latest', review);
  store.write(`reviews/review_${review.cycle}`, review);

  // Generate markdown report file for Hermes to read
  const mdPath = store.writeFile(`reviews/cycle_${review.cycle}_report.md`, review.reportText);

  return review;
}

/**
 * Analyze trade patterns — find what's working and what isn't.
 */
function analyzePatterns(trades, performance) {
  const exitTrades = trades.filter(t => t.type === 'exit');
  if (exitTrades.length < 3) {
    return { meaningful: false, message: 'Not enough trades for pattern analysis' };
  }

  // Per-symbol analysis
  const bySymbol = {};
  for (const t of exitTrades) {
    const sym = t.symbol || 'unknown';
    if (!bySymbol[sym]) bySymbol[sym] = { trades: [], wins: 0, losses: 0, totalPnl: 0 };
    bySymbol[sym].trades.push(t);
    if (t.pnl > 0) bySymbol[sym].wins++;
    else bySymbol[sym].losses++;
    bySymbol[sym].totalPnl += t.pnl || 0;
  }

  const symbolStats = Object.entries(bySymbol).map(([symbol, data]) => ({
    symbol,
    totalTrades: data.trades.length,
    winRate: (data.wins / data.trades.length) * 100,
    totalPnl: data.totalPnl,
    avgPnl: data.totalPnl / data.trades.length,
  })).sort((a, b) => b.winRate - a.winRate);

  // Best and worst performing symbols
  const bestSymbol = symbolStats[0];
  const worstSymbol = symbolStats[symbolStats.length - 1];

  // Exit reason analysis
  const byExit = {};
  for (const t of exitTrades) {
    const reason = t.exitReason || 'unknown';
    if (!byExit[reason]) byExit[reason] = { count: 0, totalPnl: 0 };
    byExit[reason].count++;
    byExit[reason].totalPnl += t.pnl || 0;
  }

  // Recent trend (last 10 trades)
  const recentTrades = exitTrades.slice(-10);
  const recentWins = recentTrades.filter(t => t.pnl > 0).length;
  const recentWinRate = recentTrades.length > 0 ? (recentWins / recentTrades.length) * 100 : 0;

  return {
    meaningful: true,
    bySymbol: symbolStats,
    bestSymbol,
    worstSymbol,
    byExitReason: byExit,
    recentWinRate,
    recentTradeCount: recentTrades.length,
  };
}

/**
 * Generate hypotheses about what's working or not.
 * These are the "why" behind performance — used by Hermes to decide what to change.
 */
function generateHypotheses(performance, tradeScores, patterns, previousReview) {
  const hypotheses = [];

  // Check Sharpe ratio
  if (performance.sharpeRatio < 0.5) {
    hypotheses.push({
      area: 'risk_adjustment',
      severity: 'high',
      hypothesis: 'Low Sharpe ratio suggests returns are inconsistent relative to risk. Consider tightening stop-losses or reducing position sizes.',
      variables: ['riskPerTrade', 'stopLossPct'],
    });
  } else if (performance.sharpeRatio > 2) {
    hypotheses.push({
      area: 'risk_adjustment',
      severity: 'low',
      hypothesis: 'Sharpe ratio is strong. Consider slightly increasing position sizes to capitalize.',
      variables: ['riskPerTrade'],
    });
  }

  // Check win rate
  if (performance.winRate < 40) {
    hypotheses.push({
      area: 'entry_quality',
      severity: 'high',
      hypothesis: 'Win rate below 40% suggests entry signals may be too aggressive. Consider raising signal threshold or increasing RSI overbought/oversold thresholds.',
      variables: ['signalThreshold', 'rsiOverbought', 'rsiOversold'],
    });
  } else if (performance.winRate > 70) {
    hypotheses.push({
      area: 'entry_quality',
      severity: 'medium',
      hypothesis: 'High win rate but check if profit factor is proportionally strong. Could be taking profits too early.',
      variables: ['riskRewardRatio', 'takeProfit'],
    });
  }

  // Check profit factor
  if (performance.profitFactor < 1.5) {
    hypotheses.push({
      area: 'reward_management',
      severity: 'high',
      hypothesis: 'Profit factor below 1.5 means winners aren\'t big enough relative to losers. Increase risk-reward ratio targets.',
      variables: ['riskRewardRatio'],
    });
  }

  // Check drawdown
  if (performance.maxDrawdown > 20) {
    hypotheses.push({
      area: 'risk_management',
      severity: 'critical',
      hypothesis: 'Drawdown exceeds 20% — reduce risk per trade and add tighter stop-losses.',
      variables: ['riskPerTrade', 'stopLossPct'],
    });
  }

  // Check average trade return
  if (performance.avgTradeReturn < 0 && performance.totalTrades > 5) {
    hypotheses.push({
      area: 'overall_strategy',
      severity: 'critical',
      hypothesis: 'Negative average return indicates the strategy is systematically losing. Consider a broader parameter reset or different indicator combination.',
      variables: ['*'], // Reset all
    });
  }

  // Symbol-specific
  if (patterns?.meaningful && patterns.bestSymbol && patterns.worstSymbol) {
    if (patterns.bestSymbol.symbol !== patterns.worstSymbol.symbol) {
      hypotheses.push({
        area: 'asset_allocation',
        severity: 'medium',
        hypothesis: `${patterns.bestSymbol.symbol} (${patterns.bestSymbol.winRate.toFixed(0)}% win rate) outperforms ${patterns.worstSymbol.symbol} (${patterns.worstSymbol.winRate.toFixed(0)}%). Consider adjusting allocation toward ${patterns.bestSymbol.symbol}.`,
        variables: ['assetWeights'],
      });
    }
  }

  // Recent trend
  if (patterns?.meaningful && patterns.recentTradeCount >= 5 && patterns.recentWinRate < 30) {
    hypotheses.push({
      area: 'regime_change',
      severity: 'high',
      hypothesis: `Recent win rate is only ${patterns.recentWinRate.toFixed(0)}% — market regime may have shifted. Consider adapting indicator parameters.`,
      variables: ['rsiPeriod', 'macdFast', 'macdSlow', 'bbPeriod'],
    });
  }

  // Check previous review's actions
  if (previousReview?.actions) {
    const prevActions = previousReview.actions.filter(a => a.status === 'implemented');
    for (const action of prevActions) {
      if (action.expectedOutcome && performance.totalTrades > previousReview.performance.totalTrades) {
        const improved = evaluateActionOutcome(action, performance, previousReview.performance);
        hypotheses.push({
          area: 'previous_change',
          severity: 'low',
          hypothesis: `Previous change "${action.description}" was ${improved ? 'beneficial' : 'not beneficial'} — ${improved ? 'keep this parameter' : 'consider reverting'}.`,
          variables: action.parameters || [],
          previousActionResult: improved ? 'positive' : 'negative',
        });
      }
    }
  }

  return hypotheses;
}

function evaluateActionOutcome(action, current, previous) {
  // Simple heuristic: check if more metrics improved than worsened
  const metrics = ['sharpeRatio', 'winRate', 'profitFactor', 'totalReturn'];
  let improvements = 0;
  for (const m of metrics) {
    if ((current[m] || 0) > (previous[m] || 0)) improvements++;
  }
  return improvements >= metrics.length / 2;
}

/**
 * Determine concrete actions based on the analysis.
 */
function determineActions(performance, goals, hypotheses) {
  const actions = [];

  // Priority: critical > high > medium > low
  const priorityMap = { critical: 0, high: 1, medium: 2, low: 3 };

  const sorted = [...hypotheses].sort((a, b) => (priorityMap[a.severity] || 99) - (priorityMap[b.severity] || 99));

  for (const h of sorted.slice(0, 3)) {
    actions.push({
      priority: h.severity,
      description: h.hypothesis,
      parameters: h.variables,
      status: 'proposed',
      expectedOutcome: `Improve ${h.area}`,
    });
  }

  // If no specific hypotheses, suggest a general parameter review
  if (actions.length === 0) {
    actions.push({
      priority: 'low',
      description: 'All metrics are healthy. Consider minor optimization of existing parameters or expanding to new assets.',
      parameters: ['*'],
      status: 'proposed',
      expectedOutcome: 'Incremental improvement',
    });
  }

  return actions;
}

export default { runReview };
