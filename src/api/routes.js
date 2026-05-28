/**
 * API Routes for the Trading Agent Server
 */
import { Router } from 'express';
import { handleWebhook, getTradingViewSetupGuide } from '../tradingview/webhook.js';
import { tick, handleTradingViewAlert } from '../papertrading/engine.js';
import { fetchPrice } from '../data/market.js';
import { getPortfolio } from '../papertrading/portfolio.js';
import store from '../data/store.js';
import * as perf from '../analytics/performance.js';
import { runReview } from '../self-improve/reviewer.js';
import { proposeOptimization, applyOptimization, loadStrategy } from '../self-improve/optimizer.js';
import { runAlertMonitor, addAlert, removeAlert } from '../alerts/monitor.js';
import * as alpaca from '../brokers/alpaca.js';
import getConfig from '../config/index.js';

const config = getConfig();
const router = Router();

// Health check
router.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    timestamp: new Date().toISOString(),
    version: '1.0.0',
    agent: 'Hermes Trading Agent',
    uptime: process.uptime(),
  });
});

// Overall status
router.get('/api/status', (req, res) => {
  const portfolio = getPortfolio();
  const trades = store.read('trades') || [];
  const cycles = store.read('cycles') || [];
  const exitTrades = trades.filter(t => t.type === 'exit');
  const totalValue = portfolio
    ? (portfolio.balances?.USD || 0) +
      (portfolio.positions || []).filter(p => p.status === 'open')
        .reduce((s, p) => s + (p.currentValue || p.quantity * p.currentPrice), 0)
    : 0;

  res.json({
    status: 'running',
    portfolio: {
      cashBalance: portfolio?.balances?.USD || 0,
      openPositions: (portfolio?.positions || []).filter(p => p.status === 'open').length,
      totalValue: Math.round(totalValue * 100) / 100,
      totalTrades: portfolio?.tradeCount || 0,
      winningTrades: portfolio?.winningTrades || 0,
      losingTrades: portfolio?.losingTrades || 0,
    },
    system: {
      totalCycles: cycles.length,
      totalAlerts: trades.filter(t => t.type === 'entry').length,
      lastCycle: cycles[cycles.length - 1]?.timestamp || null,
    },
  });
});

// Get performance metrics
router.get('/api/performance', (req, res) => {
  const trades = store.read('trades') || [];
  const portfolio = getPortfolio();
  const strategy = loadStrategy();
  const performance = perf.calcPerformance(trades, portfolio);
  const report = perf.generateReport(performance, strategy?.goals);
  res.json({ performance, report });
});

// Get trade history
router.get('/api/trades', (req, res) => {
  const trades = store.read('trades') || [];
  const limit = parseInt(req.query.limit) || 50;
  const offset = parseInt(req.query.offset) || 0;
  const filtered = trades.slice(-limit - offset, trades.length - offset || undefined);
  res.json({
    total: trades.length,
    returned: filtered.length,
    offset,
    limit,
    trades: filtered.reverse(),
  });
});

// Get portfolio
router.get('/api/portfolio', (req, res) => {
  const portfolio = getPortfolio();
  res.json(portfolio);
});

// Get current strategy config
router.get('/api/strategy', (req, res) => {
  const strategy = loadStrategy();
  res.json(strategy || {});
});

// Update strategy config
router.post('/api/strategy/update', (req, res) => {
  const { params } = req.body;
  if (!params) {
    return res.status(400).json({ error: 'Missing params' });
  }
  const { loadStrategy, saveStrategy } = require('../self-improve/optimizer.js');
  const strategy = loadStrategy() || {};
  Object.assign(strategy, params);
  if (params.weights && strategy.weights) {
    Object.assign(strategy.weights, params.weights);
  }
  saveStrategy(strategy);
  res.json({ success: true, strategy });
});

// Get recent cycles
router.get('/api/cycles', (req, res) => {
  const cycles = store.read('cycles') || [];
  const limit = parseInt(req.query.limit) || 20;
  res.json(cycles.slice(-limit).reverse());
});

// Get latest review
router.get('/api/reviews/latest', (req, res) => {
  const review = store.read('reviews/latest');
  res.json(review || { error: 'No reviews yet' });
});

// Run a manual review cycle
router.post('/api/review', async (req, res) => {
  try {
    const review = await runReview();
    res.json(review);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Run a manual trading tick
router.post('/api/tick', async (req, res) => {
  try {
    const result = await tick(config.strategy);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Propose optimization
router.get('/api/optimize/propose', (req, res) => {
  const review = store.read('reviews/latest');
  if (!review) return res.json({ error: 'Run a review first' });
  const proposal = proposeOptimization(review);
  res.json(proposal);
});

// Apply optimization
router.post('/api/optimize/apply', (req, res) => {
  const proposal = req.body;
  if (!proposal) return res.status(400).json({ error: 'Missing proposal' });
  const result = applyOptimization(proposal);
  res.json(result);
});

// Full optimization cycle
router.post('/api/optimize/cycle', async (req, res) => {
  try {
    const { runOptimizationCycle } = await import('../self-improve/optimizer.js');
    const result = await runOptimizationCycle();
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// TradingView webhook endpoint
router.post('/webhook/tradingview', async (req, res) => {
  const { valid, alert, error } = await handleWebhook(req.body);
  if (!valid) {
    return res.status(401).json({ error });
  }

  try {
    const result = await handleTradingViewAlert(alert);
    // If the handler returned a direct response (buy/sell executed), pass it through
    if (result?.success !== undefined) {
      return res.json(result);
    }
    // Otherwise, it's from the tick() fallback
    res.json({
      success: true,
      alert,
      executions: result.executions || [],
      portfolio: result.portfolio || {},
    });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// TradingView setup guide
router.get('/api/tradingview/setup', (req, res) => {
  const guide = getTradingViewSetupGuide();
  res.json(guide);
});

// Get webhook alerts log
router.get('/api/webhook/alerts', (req, res) => {
  const alerts = store.read('webhook_alerts') || [];
  const limit = parseInt(req.query.limit) || 20;
  res.json(alerts.slice(-limit).reverse());
});

// Diagnostic: test data sources
router.get('/api/diagnose', async (req, res) => {
  const results = {};
  for (const asset of [{s:'BTC',c:'crypto'},{s:'ETH',c:'crypto'},{s:'AAPL',c:'stock'},{s:'SPY',c:'stock'},{s:'EURUSD',c:'forex'}]) {
    try {
      const start = Date.now();
      const price = await fetchPrice(asset.s, asset.c);
      results[asset.s] = { price, ms: Date.now() - start };
    } catch (e) {
      results[asset.s] = { error: e.message };
    }
  }
  res.json(results);
});

// === Free Price Alert Monitor ===

// Run the alert monitor manually
router.post('/api/alerts/run', async (req, res) => {
  try {
    const result = await runAlertMonitor();
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// List all alert rules
router.get('/api/alerts', (req, res) => {
  const alerts = store.read('alerts') || [];
  res.json(alerts);
});

// Add a new alert rule
router.post('/api/alerts', (req, res) => {
  const { symbol, assetClass, condition, value, action, message, riskPerTrade, stopLossPct, riskRewardRatio, repeatable } = req.body;
  if (!symbol || condition === undefined || value === undefined) {
    return res.status(400).json({ error: 'symbol, condition, and value required' });
  }
  const result = addAlert({
    symbol: symbol.toUpperCase(),
    assetClass: assetClass || 'crypto',
    condition: condition || 'gte',
    value,
    action: action || 'buy',
    message: message || `${symbol} ${condition} ${value}`,
    riskPerTrade,
    stopLossPct,
    riskRewardRatio,
    repeatable: repeatable || false,
  });
  res.json(result);
});

// Remove an alert rule
router.delete('/api/alerts/:id', (req, res) => {
  const result = removeAlert(req.params.id);
  res.json(result);
});

// Reset all triggered alerts
router.post('/api/alerts/reset', (req, res) => {
  const alerts = store.read('alerts') || [];
  for (const a of alerts) a.triggered = false;
  store.write('alerts', alerts);
  res.json({ message: 'All alerts reset', count: alerts.length });
});

// === Alpaca Integration ===

// Connect Alpaca with API keys
router.post('/api/alpaca/connect', async (req, res) => {
  try {
    const { keyId, secretKey, paper } = req.body;
    if (!keyId || !secretKey) {
      return res.status(400).json({ error: 'keyId and secretKey required' });
    }
    const result = alpaca.connect(keyId, secretKey, paper !== false);
    // Also save to env for persistence across restarts
    store.write('alpaca/credentials', {
      keyId: keyId.slice(0, 8) + '...',
      hasSecret: !!secretKey,
      paper: paper !== false,
    });
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Disconnect Alpaca
router.post('/api/alpaca/disconnect', (req, res) => {
  const result = alpaca.disconnect();
  res.json(result);
});

// Alpaca connection status
router.get('/api/alpaca/status', (req, res) => {
  const status = alpaca.getStatus();
  const credentials = store.read('alpaca/credentials') || {};
  res.json({ ...status, ...credentials });
});

// Get Alpaca account info
router.get('/api/alpaca/account', async (req, res) => {
  try {
    if (!alpaca.isConnected()) {
      return res.status(400).json({ error: 'Alpaca not connected' });
    }
    const account = await alpaca.getAccount();
    res.json(account);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Get Alpaca positions
router.get('/api/alpaca/positions', async (req, res) => {
  try {
    if (!alpaca.isConnected()) {
      return res.status(400).json({ error: 'Alpaca not connected' });
    }
    const positions = await alpaca.getPositions();
    res.json(positions);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Get Alpaca orders
router.get('/api/alpaca/orders', async (req, res) => {
  try {
    if (!alpaca.isConnected()) {
      return res.status(400).json({ error: 'Alpaca not connected' });
    }
    const orders = await alpaca.getOrders(req.query.limit, req.query.status);
    res.json(orders);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Place an order via Alpaca
router.post('/api/alpaca/order', async (req, res) => {
  try {
    if (!alpaca.isConnected()) {
      return res.status(400).json({ error: 'Alpaca not connected' });
    }
    const result = await alpaca.placeOrder(req.body);
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// Sync portfolio with Alpaca
router.post('/api/alpaca/sync', async (req, res) => {
  try {
    if (!alpaca.isConnected()) {
      return res.status(400).json({ error: 'Alpaca not connected' });
    }
    const result = await alpaca.syncPortfolio();
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

export default router;
