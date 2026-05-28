/**
 * Performance Analytics
 * Calculates trading metrics: Sharpe ratio, win rate, profit factor, max drawdown, etc.
 */
import store from '../data/store.js';

export function calcPerformance(trades, portfolio) {
  if (!trades || trades.length === 0) {
    return {
      totalTrades: 0,
      winRate: 0,
      profitFactor: 0,
      sharpeRatio: 0,
      maxDrawdown: 0,
      currentDrawdown: 0,
      totalReturn: 0,
      avgReturn: 0,
    };
  }

  const exitTrades = trades.filter(t => t.type === 'exit' && t.pnl !== undefined);
  const totalTrades = exitTrades.length;
  if (totalTrades === 0) return { totalTrades: 0, winRate: 0, profitFactor: 0, sharpeRatio: 0, maxDrawdown: 0, currentDrawdown: 0, totalReturn: 0, avgReturn: 0 };

  const winning = exitTrades.filter(t => t.pnl > 0);
  const losing = exitTrades.filter(t => t.pnl < 0);
  const winRate = (winning.length / totalTrades) * 100;

  const grossProfit = winning.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losing.reduce((s, t) => s + t.pnl, 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;

  // Sharpe ratio (using daily returns approximation)
  const returns = exitTrades.map(t => t.pnlPercent || 0);
  const avgReturn = returns.reduce((s, r) => s + r, 0) / returns.length;
  const stdDev = Math.sqrt(returns.reduce((s, r) => s + (r - avgReturn) ** 2, 0) / returns.length);
  const sharpeRatio = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0; // Annualized

  // Max drawdown (from cycles data)
  const cycles = store.read('cycles') || [];
  let peak = portfolio?.peakBalance || 100000;
  let maxDD = 0;
  for (const cycle of cycles) {
    if (cycle.totalValue > peak) peak = cycle.totalValue;
    const dd = (peak - cycle.totalValue) / peak;
    if (dd > maxDD) maxDD = dd;
  }

  // Current drawdown
  const totalValue = portfolio?.totalValue || portfolio?.balances?.USD || 100000;
  const currentDD = peak > 0 ? (peak - totalValue) / peak : 0;

  // Total return
  const initialBalance = 100000; // Default starting balance
  const totalReturn = ((totalValue - initialBalance) / initialBalance) * 100;

  // Average trade return
  const avgTradeReturn = returns.length > 0
    ? returns.reduce((s, r) => s + r, 0) / returns.length
    : 0;

  // Largest winning and losing trades
  const largestWin = winning.length > 0 ? Math.max(...winning.map(t => t.pnlPercent)) : 0;
  const largestLoss = losing.length > 0 ? Math.min(...losing.map(t => t.pnlPercent)) : 0;

  // Consecutive wins/losses
  let consWins = 0, consLosses = 0, maxConsWins = 0, maxConsLosses = 0;
  for (const t of exitTrades) {
    if (t.pnl > 0) {
      consWins++;
      consLosses = 0;
      if (consWins > maxConsWins) maxConsWins = consWins;
    } else {
      consLosses++;
      consWins = 0;
      if (consLosses > maxConsLosses) maxConsLosses = consLosses;
    }
  }

  return {
    totalTrades,
    winningTrades: winning.length,
    losingTrades: losing.length,
    winRate: Math.round(winRate * 100) / 100,
    profitFactor: Math.round(profitFactor * 100) / 100,
    sharpeRatio: Math.round(sharpeRatio * 100) / 100,
    maxDrawdown: Math.round(maxDD * 10000) / 100,
    currentDrawdown: Math.round(currentDD * 10000) / 100,
    totalReturn: Math.round(totalReturn * 100) / 100,
    avgTradeReturn: Math.round(avgTradeReturn * 100) / 100,
    largestWin: Math.round(largestWin * 100) / 100,
    largestLoss: Math.round(largestLoss * 100) / 100,
    maxConsecutiveWins: maxConsWins,
    maxConsecutiveLosses: maxConsLosses,
  };
}

export function generateReport(performance, goals) {
  const lines = [];
  lines.push('# Trading Performance Report');
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push('');
  lines.push('## Key Metrics');
  lines.push(`- Total Trades: ${performance.totalTrades}`);
  lines.push(`- Win Rate: ${performance.winRate}%`);
  lines.push(`- Profit Factor: ${performance.profitFactor}`);
  lines.push(`- Sharpe Ratio: ${performance.sharpeRatio}`);
  lines.push(`- Total Return: ${performance.totalReturn}%`);
  lines.push(`- Max Drawdown: ${performance.maxDrawdown}%`);
  lines.push(`- Current Drawdown: ${performance.currentDrawdown}%`);
  lines.push(`- Average Trade Return: ${performance.avgTradeReturn}%`);
  lines.push(`- Largest Win: ${performance.largestWin}%`);
  lines.push(`- Largest Loss: ${performance.largestLoss}%`);
  lines.push(`- Max Consecutive Wins: ${performance.maxConsecutiveWins}`);
  lines.push(`- Max Consecutive Losses: ${performance.maxConsecutiveLosses}`);
  lines.push('');

  if (goals) {
    lines.push('## Goals vs Actual');
    if (goals.minSharpe) lines.push(`- Sharpe: Target ≥${goals.minSharpe} | Actual ${performance.sharpeRatio} ${performance.sharpeRatio >= goals.minSharpe ? '✓' : '✗'}`);
    if (goals.maxDrawdown) lines.push(`- Max Drawdown: Target ≤${goals.maxDrawdown}% | Actual ${performance.maxDrawdown}% ${performance.maxDrawdown <= goals.maxDrawdown ? '✓' : '✗'}`);
    if (goals.targetReturn30d) lines.push(`- 30d Return: Target ≥${goals.targetReturn30d}% | Actual ${performance.totalReturn}% ${performance.totalReturn >= goals.targetReturn30d ? '✓' : '✗'}`);
    if (goals.minWinRate) lines.push(`- Win Rate: Target ≥${goals.minWinRate}% | Actual ${performance.winRate}% ${performance.winRate >= goals.minWinRate ? '✓' : '✗'}`);
    lines.push('');
    lines.push('## Goal Status');
    const allGoals = [
      goals.minSharpe ? performance.sharpeRatio >= goals.minSharpe : true,
      goals.maxDrawdown ? performance.maxDrawdown <= goals.maxDrawdown : true,
      goals.targetReturn30d ? performance.totalReturn >= goals.targetReturn30d : true,
      goals.minWinRate ? performance.winRate >= goals.minWinRate : true,
    ];
    const met = allGoals.filter(Boolean).length;
    const total = allGoals.length;
    lines.push(`- ${met}/${total} goals met (${Math.round(met / total * 100)}%)`);
    if (met < total) {
      lines.push('- Action required: Review strategy parameters');
    }
  }

  return lines.join('\n');
}

export default { calcPerformance, generateReport };
