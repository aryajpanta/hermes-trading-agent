/**
 * Paper Trading Engine
 * Core loop: receive signals → validate → execute → log
 */
import { evaluate } from '../strategy/engine.js';
import { fetchPrice, fetchHistoricalData } from '../data/market.js';
import { calcStopLoss, calcTakeProfit } from '../strategy/risk.js';
import store from '../data/store.js';
import * as portfolio from './portfolio.js';
import getConfig from '../config/index.js';

const config = getConfig();

/**
 * Main tick function — runs on each TradingView webhook or scheduled cycle.
 * Fetches market data, evaluates strategy, executes paper trades.
 */
export async function tick(strategyConfig) {
  const params = strategyConfig || config.strategy;
  const port = portfolio.loadPortfolio(config.paperBalance);

  // Get the list of tracked assets
  const assets = params.assets || [
    { symbol: 'BTC', assetClass: 'crypto' },
    { symbol: 'ETH', assetClass: 'crypto' },
    { symbol: 'SOL', assetClass: 'crypto' },
    { symbol: 'AAPL', assetClass: 'stock' },
    { symbol: 'SPY', assetClass: 'stock' },
  ];

  // Fetch current prices
  const priceData = {};
  for (const asset of assets) {
    const price = await fetchPrice(asset.symbol, asset.assetClass);
    if (price) {
      priceData[asset.symbol] = price;
    }
  }

  // Update open positions with current prices
  portfolio.updatePositionPrices(port, priceData);

  // Check stop-losses and take-profits
  for (const pos of port.positions) {
    if (pos.status !== 'open') continue;
    const currentPrice = priceData[pos.symbol];
    if (!currentPrice) continue;

    if (pos.side === 'long') {
      if (pos.stopLoss && currentPrice <= pos.stopLoss) {
        portfolio.closePosition(port, pos.id, currentPrice, 'stop_loss');
      } else if (pos.takeProfit && currentPrice >= pos.takeProfit) {
        portfolio.closePosition(port, pos.id, currentPrice, 'take_profit');
      }
    }
  }

  // Fetch historical data and evaluate for each asset
  const signals = [];
  for (const asset of assets) {
    const candles = await fetchHistoricalData(asset.symbol, asset.assetClass, 60);
    const signal = evaluate(candles, params);
    signals.push({ symbol: asset.symbol, assetClass: asset.assetClass, ...signal });
  }

  // Execute signals
  const executions = [];
  for (const sig of signals) {
    if (sig.signal === 'hold') continue;

    const existingPos = portfolio.hasOpenPosition(port, sig.symbol);

    if (sig.signal === 'buy' && !existingPos) {
      const quantity = config.paperBalance / sig.entryPrice * 0.1; // 10% of balance per trade
      const pos = portfolio.openPosition(port, {
        symbol: sig.symbol,
        assetClass: sig.assetClass,
        side: 'long',
        quantity: quantity > 0 ? quantity : 0.001,
        entryPrice: sig.entryPrice,
        stopLoss: sig.stopLoss,
        takeProfit: sig.takeProfit,
        reason: sig.reason,
      });
      executions.push({ type: 'entry', symbol: sig.symbol, price: sig.entryPrice, confidence: sig.confidence, reason: sig.reason });
    } else if (sig.signal === 'sell' && existingPos) {
      const pos = port.positions.find(p => p.symbol === sig.symbol && p.status === 'open');
      if (pos) {
        portfolio.closePosition(port, pos.id, sig.entryPrice, 'signal_exit');
        executions.push({ type: 'exit', symbol: sig.symbol, price: sig.entryPrice, reason: sig.reason });
      }
    }
  }

  // Log the cycle
  const totalValue = portfolio.getTotalValue(port);
  store.append('cycles', {
    timestamp: new Date().toISOString(),
    signals: signals.map(s => ({ symbol: s.symbol, signal: s.signal, confidence: s.confidence, score: s.score })),
    executions,
    totalValue,
    cashBalance: port.balances.USD,
    openPositions: port.positions.filter(p => p.status === 'open').length,
    drawdown: port.peakBalance ? (port.peakBalance - totalValue) / port.peakBalance : 0,
  });

  return {
    signals,
    executions,
    portfolio: {
      totalValue,
      cash: port.balances.USD,
      openPositions: port.positions.filter(p => p.status === 'open').length,
      drawdown: port.peakBalance ? (port.peakBalance - totalValue) / port.peakBalance : 0,
      winRate: port.tradeCount > 0 ? (port.winningTrades / port.tradeCount) * 100 : 0,
      tradeCount: port.tradeCount,
    },
  };
}

/**
 * Handle a TradingView webhook alert.
 * @param {Object} alert - Parsed TradingView alert payload
 */
export async function handleTradingViewAlert(alert) {
  const strategyConfig = config.strategy;
  const port = portfolio.loadPortfolio(config.paperBalance);

  // Override asset if specified in the alert
  if (alert.symbol) {
    strategyConfig.assets = strategyConfig.assets || [];
    const existing = strategyConfig.assets.find(a => a.symbol === alert.symbol);
    if (!existing) {
      strategyConfig.assets.push({
        symbol: alert.symbol,
        assetClass: alert.assetClass || 'crypto',
      });
    }
  }

  // If the alert contains a direct buy/sell action, execute it
  if (alert.action === 'buy' || alert.action === 'sell') {
    const symbol = alert.symbol;
    const price = alert.price > 0 ? alert.price : (await fetchPrice(symbol, alert.assetClass));

    if (!price) {
      return { error: `Could not get price for ${symbol}` };
    }

    // Update open positions with current price
    portfolio.updatePositionPrices(port, { [symbol]: price });

    if (alert.action === 'buy' && !portfolio.hasOpenPosition(port, symbol)) {
      // Calculate position size based on strategy config
      const riskPerTrade = strategyConfig.riskPerTrade || 0.015;
      const balance = port.balances?.USD || 0;
      const positionValue = balance * riskPerTrade * 10; // ~15% of balance per trade
      const quantity = positionValue / price;

      // Get strategy-calculated risk params
      const stopLossPct = strategyConfig.stopLossPct || 0.02;
      const riskRewardRatio = strategyConfig.riskRewardRatio || 2;
      const stopLoss = calcStopLoss(price, 'long', stopLossPct);
      const takeProfit = calcTakeProfit(price, 'long', riskRewardRatio * stopLossPct);

      const pos = portfolio.openPosition(port, {
        symbol,
        assetClass: alert.assetClass || 'crypto',
        side: 'long',
        quantity,
        entryPrice: price,
        stopLoss,
        takeProfit,
        reason: `TradingView alert: ${alert.message || alert.action}`,
      });

      // Log the webhook execution
      store.append('webhook_executions', {
        timestamp: new Date().toISOString(),
        type: 'entry',
        symbol,
        price,
        quantity,
        positionId: pos.id,
        message: alert.message,
      });

      const totalValue = portfolio.getTotalValue(port);
      return {
        success: true,
        action: 'buy_executed',
        symbol,
        price,
        quantity,
        position: pos,
        portfolio: {
          totalValue,
          cash: port.balances?.USD,
          openPositions: port.positions.filter(p => p.status === 'open').length,
          tradeCount: port.tradeCount,
        },
      };
    } else if (alert.action === 'sell') {
      // Close existing position for this symbol
      const existingPos = port.positions.find(p => p.symbol === symbol && p.status === 'open');
      if (existingPos) {
        const closed = portfolio.closePosition(port, existingPos.id, price, 'tradingview_signal');
        return {
          success: true,
          action: 'sell_executed',
          symbol,
          exitPrice: price,
          pnl: closed?.pnl,
          pnlPercent: closed?.pnlPercent,
          portfolio: {
            totalValue: portfolio.getTotalValue(port),
            cash: port.balances?.USD,
            openPositions: port.positions.filter(p => p.status === 'open').length,
            tradeCount: port.tradeCount,
          },
        };
      }
    }
  }

  // Fall back to strategy evaluation tick
  return await tick(strategyConfig);
}

export default { tick, handleTradingViewAlert };
