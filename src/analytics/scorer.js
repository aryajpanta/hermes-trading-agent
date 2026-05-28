/**
 * Trade Scorer
 * Scores each trade based on multiple factors.
 * Used by Hermes to evaluate trade quality beyond just P&L.
 */
import store from '../data/store.js';

/**
 * Score a single trade on quality dimensions.
 * Returns a score 0-100.
 */
export function scoreTrade(trade, strategyGoals) {
  if (!trade) return 0;

  const scores = {
    profitability: scoreProfitability(trade),
    riskManagement: scoreRiskManagement(trade),
    strategyAdherence: scoreStrategyAdherence(trade, strategyGoals),
    timing: scoreTiming(trade),
    consistency: 50, // Base — will be updated with context
  };

  const weights = {
    profitability: 0.35,
    riskManagement: 0.25,
    strategyAdherence: 0.20,
    timing: 0.10,
    consistency: 0.10,
  };

  const total = Object.entries(weights).reduce((sum, [key, weight]) => {
    return sum + (scores[key] || 0) * weight;
  }, 0);

  return {
    total: Math.round(total),
    components: scores,
    grade: total >= 80 ? 'A' : total >= 65 ? 'B' : total >= 50 ? 'C' : total >= 35 ? 'D' : 'F',
  };
}

function scoreProfitability(trade) {
  if (trade.type === 'entry') return 50; // Neutral for entries
  const pnl = trade.pnlPercent || 0;
  if (pnl > 5) return 100;
  if (pnl > 2) return 85;
  if (pnl > 0) return 70;
  if (pnl > -2) return 40;
  if (pnl > -5) return 20;
  return 0;
}

function scoreRiskManagement(trade) {
  let score = 50;
  // Was stop loss respected?
  if (trade.exitReason === 'stop_loss') score -= 20;
  if (trade.exitReason === 'take_profit') score += 20;
  // Risk-reward ratio
  if (trade.pnlPercent && trade.entryPrice) {
    const risk = Math.abs(trade.stopLoss - trade.entryPrice) / trade.entryPrice;
    const reward = trade.takeProfit ? Math.abs(trade.takeProfit - trade.entryPrice) / trade.entryPrice : 0;
    if (risk > 0 && reward / risk >= 2) score += 15;
    else if (risk > 0 && reward / risk >= 1) score += 5;
    else score -= 10;
  }
  return Math.max(0, Math.min(100, score));
}

function scoreStrategyAdherence(trade, goals) {
  if (!goals) return 50;
  let score = 50;
  if (trade.pnlPercent && goals.maxDrawdown) {
    if (Math.abs(trade.pnlPercent) <= goals.maxDrawdown) score += 20;
    else score -= 20;
  }
  if (trade.exitReason === 'signal_exit') score += 15;
  if (trade.exitReason === 'manual') score -= 10;
  return Math.max(0, Math.min(100, score));
}

function scoreTiming(trade) {
  // Simple: exits during market hours score higher (less slippage)
  // Future: could compare entry/exit to optimal
  return 60;
}

/**
 * Score all trades and return aggregate stats.
 */
export function scoreAllTrades(trades, strategyGoals) {
  const exitTrades = trades.filter(t => t.type === 'exit');
  if (exitTrades.length === 0) return { averageScore: 0, grades: {}, count: 0 };

  const scored = exitTrades.map(t => ({
    trade: t.symbol || t.positionId,
    ...scoreTrade(t, strategyGoals),
  }));

  const avgScore = scored.reduce((s, t) => s + t.total, 0) / scored.length;
  const grades = {};
  for (const s of scored) {
    grades[s.grade] = (grades[s.grade] || 0) + 1;
  }

  // Component averages
  const avgComponents = {};
  for (const key of Object.keys(scored[0]?.components || {})) {
    avgComponents[key] = scored.reduce((s, t) => s + (t.components[key] || 0), 0) / scored.length;
  }

  return {
    averageScore: Math.round(avgScore),
    grades,
    totalScored: scored.length,
    averageComponents: avgComponents,
  };
}

export default { scoreTrade, scoreAllTrades };
