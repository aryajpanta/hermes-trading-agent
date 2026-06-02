/**
 * Strategy Historical Backtester
 * Simulates performance of a parameter configuration against historical OHLCV data.
 */
import { evaluate } from './engine.js';
import { calcStopLoss, calcTakeProfit } from './risk.js';

/**
 * Runs a backtest for a single asset.
 * @param {Array} candles - Array of OHLCV candles
 * @param {Object} params - Strategy parameters to test
 * @param {number} initialBalance - Initial balance (default 100,000)
 * @returns {Object} Backtest results (returns, win rate, Sharpe, drawdown, trades list)
 */
export function runBacktest(candles, params, initialBalance = 100000) {
  if (!candles || candles.length < 50) {
    return {
      totalTrades: 0,
      winRate: 0,
      profitFactor: 0,
      sharpeRatio: 0,
      maxDrawdown: 0,
      totalReturn: 0,
      finalBalance: initialBalance,
      trades: [],
    };
  }

  let balance = initialBalance;
  let activePosition = null;
  const trades = [];
  const balanceHistory = [initialBalance];
  let peakBalance = initialBalance;
  let maxDrawdown = 0;

  // We start after candle 50 to have enough history for indicators
  for (let i = 50; i < candles.length; i++) {
    const candlesSlice = candles.slice(0, i + 1);
    const currentCandle = candles[i];
    const currentPrice = currentCandle.close;

    // 1. Check exit conditions if we have an active position
    if (activePosition) {
      let exitReason = null;
      let exitPrice = null;

      // Check Stop Loss
      if (activePosition.side === 'long') {
        if (currentCandle.low <= activePosition.stopLoss) {
          exitReason = 'stop_loss';
          exitPrice = activePosition.stopLoss; // Fill at SL boundary
        } else if (currentCandle.high >= activePosition.takeProfit) {
          exitReason = 'take_profit';
          exitPrice = activePosition.takeProfit; // Fill at TP boundary
        }
      }

      if (exitReason) {
        // Close position
        const entryValue = activePosition.quantity * activePosition.entryPrice;
        const exitValue = activePosition.quantity * exitPrice;
        const pnl = exitValue - entryValue;
        const pnlPercent = (pnl / entryValue) * 100;

        balance += exitValue;
        trades.push({
          type: 'exit',
          symbol: activePosition.symbol,
          entryPrice: activePosition.entryPrice,
          exitPrice,
          quantity: activePosition.quantity,
          pnl,
          pnlPercent,
          exitReason,
          timestamp: currentCandle.timestamp,
        });

        activePosition = null;
      }
    }

    // 2. Evaluate new signals
    const evaluation = evaluate(candlesSlice, params);
    const signal = evaluation.signal;

    if (signal === 'buy' && !activePosition) {
      // Sizing logic: 10% of current balance
      const riskPerTrade = params.riskPerTrade || 0.015;
      const positionValue = balance * 0.1; 
      const quantity = positionValue / currentPrice;

      if (balance >= positionValue && quantity > 0) {
        balance -= positionValue;
        activePosition = {
          symbol: 'BACKTEST',
          side: 'long',
          quantity,
          entryPrice: currentPrice,
          stopLoss: evaluation.stopLoss || calcStopLoss(currentPrice, 'long', params.stopLossPct || 0.02),
          takeProfit: evaluation.takeProfit || calcTakeProfit(currentPrice, 'long', (params.riskRewardRatio || 2) * (params.stopLossPct || 0.02)),
        };

        trades.push({
          type: 'entry',
          symbol: 'BACKTEST',
          entryPrice: currentPrice,
          quantity,
          timestamp: currentCandle.timestamp,
        });
      }
    } else if (signal === 'sell' && activePosition) {
      // Signal exit
      const entryValue = activePosition.quantity * activePosition.entryPrice;
      const exitValue = activePosition.quantity * currentPrice;
      const pnl = exitValue - entryValue;
      const pnlPercent = (pnl / entryValue) * 100;

      balance += exitValue;
      trades.push({
        type: 'exit',
        symbol: activePosition.symbol,
        entryPrice: activePosition.entryPrice,
        exitPrice: currentPrice,
        quantity: activePosition.quantity,
        pnl,
        pnlPercent,
        exitReason: 'signal_exit',
        timestamp: currentCandle.timestamp,
      });

      activePosition = null;
    }

    // Track total value history for drawdown
    const currentTotalValue = balance + (activePosition ? activePosition.quantity * currentPrice : 0);
    balanceHistory.push(currentTotalValue);

    if (currentTotalValue > peakBalance) {
      peakBalance = currentTotalValue;
    }
    const drawdown = (peakBalance - currentTotalValue) / peakBalance;
    if (drawdown > maxDrawdown) {
      maxDrawdown = drawdown;
    }
  }

  // Close any remaining position at the end of the test
  if (activePosition) {
    const lastCandle = candles[candles.length - 1];
    const entryValue = activePosition.quantity * activePosition.entryPrice;
    const exitValue = activePosition.quantity * lastCandle.close;
    const pnl = exitValue - entryValue;
    const pnlPercent = (pnl / entryValue) * 100;

    balance += exitValue;
    trades.push({
      type: 'exit',
      symbol: activePosition.symbol,
      entryPrice: activePosition.entryPrice,
      exitPrice: lastCandle.close,
      quantity: activePosition.quantity,
      pnl,
      pnlPercent,
      exitReason: 'end_of_data',
      timestamp: lastCandle.timestamp,
    });
  }

  // Calculate metrics
  const exitTrades = trades.filter(t => t.type === 'exit');
  const totalTrades = exitTrades.length;
  const winning = exitTrades.filter(t => t.pnl > 0);
  const losing = exitTrades.filter(t => t.pnl < 0);
  const winRate = totalTrades > 0 ? (winning.length / totalTrades) * 100 : 0;

  const grossProfit = winning.reduce((s, t) => s + t.pnl, 0);
  const grossLoss = Math.abs(losing.reduce((s, t) => s + t.pnl, 0));
  const profitFactor = grossLoss > 0 ? grossProfit / grossLoss : grossProfit > 0 ? Infinity : 0;

  // Sharpe ratio
  const returns = exitTrades.map(t => t.pnlPercent || 0);
  let sharpeRatio = 0;
  if (returns.length > 1) {
    const avgReturn = returns.reduce((s, r) => s + r, 0) / returns.length;
    const variance = returns.reduce((s, r) => s + (r - avgReturn) ** 2, 0) / (returns.length - 1);
    const stdDev = Math.sqrt(variance);
    sharpeRatio = stdDev > 0 ? (avgReturn / stdDev) * Math.sqrt(252) : 0;
  }

  const totalReturn = ((balance - initialBalance) / initialBalance) * 100;

  return {
    totalTrades,
    winRate: Math.round(winRate * 100) / 100,
    profitFactor: profitFactor === Infinity ? 999 : Math.round(profitFactor * 100) / 100,
    sharpeRatio: Math.round(sharpeRatio * 100) / 100,
    maxDrawdown: Math.round(maxDrawdown * 10000) / 100,
    totalReturn: Math.round(totalReturn * 100) / 100,
    finalBalance: Math.round(balance * 100) / 100,
    trades: exitTrades,
  };
}

export default { runBacktest };
