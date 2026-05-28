/**
 * Risk Management
 * Position sizing, stop-loss, take-profit, max drawdown monitoring.
 */

/**
 * Calculate position size using Kelly Criterion (simplified) or fixed-percentage.
 * @param {Object} params
 * @param {number} params.balance - Account balance
 * @param {number} params.riskPerTrade - % risk per trade (0.01 = 1%)
 * @param {number} params.stopLossPct - Stop loss % from entry
 * @param {number} params.confidence - Strategy confidence (0-1)
 * @returns {number} Position size in quote currency
 */
export function calcPositionSize({ balance, riskPerTrade = 0.01, stopLossPct = 0.02, confidence = 0.5 }) {
  if (stopLossPct <= 0) return balance * riskPerTrade;
  // Kelly-inspired: f* = (bp - q) / b where b = odds, p = win prob
  const b = 1 / stopLossPct; // reward:risk ratio (assuming 1:1 for simplicity)
  const p = confidence;
  const q = 1 - p;
  const kellyFraction = Math.max(0, Math.min(0.25, (b * p - q) / b));
  // Use half-kelly for safety, scaled by riskPerTrade
  const fraction = (kellyFraction * 0.5) || riskPerTrade;
  return balance * fraction;
}

export function calcStopLoss(entryPrice, direction, stopLossPct) {
  if (direction === 'long') {
    return entryPrice * (1 - stopLossPct);
  }
  return entryPrice * (1 + stopLossPct);
}

export function calcTakeProfit(entryPrice, direction, riskRewardRatio) {
  if (direction === 'long') {
    return entryPrice * (1 + riskRewardRatio);
  }
  return entryPrice * (1 - riskRewardRatio);
}

/**
 * Check if current drawdown exceeds max allowed.
 */
export function checkMaxDrawdown(peakBalance, currentBalance, maxDrawdownPct) {
  if (peakBalance <= 0) return true;
  const drawdown = (peakBalance - currentBalance) / peakBalance;
  return drawdown <= maxDrawdownPct;
}

export function calcDrawdown(peakBalance, currentBalance) {
  if (peakBalance <= 0) return 0;
  return (peakBalance - currentBalance) / peakBalance;
}

export default {
  calcPositionSize,
  calcStopLoss,
  calcTakeProfit,
  checkMaxDrawdown,
  calcDrawdown,
};
