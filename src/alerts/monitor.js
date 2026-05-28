/**
 * Price Alert Monitor
 * Replaces TradingView webhooks — completely free.
 * Runs on a schedule, checks prices, triggers trades when conditions are met.
 */
import store from '../data/store.js';
import { fetchPrice } from '../data/market.js';
import * as portfolio from '../papertrading/portfolio.js';
import { calcStopLoss, calcTakeProfit } from '../strategy/risk.js';
import * as alpaca from '../brokers/alpaca.js';
import getConfig from '../config/index.js';

const config = getConfig();

/**
 * Load alert rules from data/alerts.json
 * Each rule:
 * {
 *   id: "btc_75k",
 *   symbol: "BTC",
 *   assetClass: "crypto",
 *   condition: "gte",         // gte, lte, cross_above, cross_below
 *   value: 75000,
 *   action: "buy",            // buy, sell
 *   message: "BTC crossed 75k",
 *   triggered: false          // Reset when condition clears
 * }
 */
function loadAlerts() {
  return store.read('alerts') || [];
}

function saveAlerts(alerts) {
  store.write('alerts', alerts);
}

/**
 * Check a single alert condition.
 */
function checkCondition(currentPrice, condition, threshold) {
  switch (condition) {
    case 'gte':       return currentPrice >= threshold;
    case 'lte':       return currentPrice <= threshold;
    case 'cross_above': return currentPrice >= threshold;
    case 'cross_below': return currentPrice <= threshold;
    default:          return false;
  }
}

/**
 * Run the alert monitor — checks all rules and executes triggered ones.
 */
export async function runAlertMonitor() {
  const alerts = loadAlerts();
  if (alerts.length === 0) {
    return { message: 'No alerts configured', triggered: [] };
  }

  const triggered = [];
  const defaults = config.strategy || {};

  for (const alert of alerts) {
    // Skip already-triggered alerts (wait for manual reset or condition reversal)
    if (alert.triggered && !alert.repeatable) continue;

    // Fetch current price
    const price = await fetchPrice(alert.symbol, alert.assetClass);
    if (!price) {
      console.log(`[Alerts] Could not fetch price for ${alert.symbol}`);
      continue;
    }

    // Check condition
    const met = checkCondition(price, alert.condition, alert.value);
    if (!met) {
      // If price moved away, reset triggered flag so it can fire again
      if (alert.triggered) {
        alert.triggered = false;
      }
      continue;
    }

    // Already triggered — skip unless repeatable
    if (alert.triggered) continue;

    // Condition met! Execute the trade on paper trading engine
    const port = portfolio.loadPortfolio(config.paperBalance);
    const balance = port.balances?.USD || 0;
    const riskPerTrade = alert.riskPerTrade || defaults.riskPerTrade || 0.015;
    const positionValue = balance * riskPerTrade * 10;
    const quantity = positionValue / price;

    const stopLossPct = alert.stopLossPct || defaults.stopLossPct || 0.02;
    const riskRewardRatio = alert.riskRewardRatio || defaults.riskRewardRatio || 2;
    const stopLoss = calcStopLoss(price, 'long', stopLossPct);
    const takeProfit = calcTakeProfit(price, 'long', riskRewardRatio * stopLossPct);

    // Update portfolios
    portfolio.updatePositionPrices(port, { [alert.symbol]: price });

    let execution;
    if (alert.action === 'buy' && !portfolio.hasOpenPosition(port, alert.symbol)) {
      const pos = portfolio.openPosition(port, {
        symbol: alert.symbol,
        assetClass: alert.assetClass || 'crypto',
        side: 'long',
        quantity,
        entryPrice: price,
        stopLoss,
        takeProfit,
        reason: `Alert: ${alert.message || alert.symbol} ${alert.condition} ${alert.value}`,
      });
      execution = { type: 'entry', symbol: alert.symbol, price, quantity, positionId: pos.id };
    } else if (alert.action === 'sell') {
      const existingPos = port.positions.find(p => p.symbol === alert.symbol && p.status === 'open');
      if (existingPos) {
        const closed = portfolio.closePosition(port, existingPos.id, price, 'alert_signal');
        execution = { type: 'exit', symbol: alert.symbol, price, pnl: closed?.pnl };
      }
    }

    if (execution) {
      alert.triggered = true;
      alert.lastTriggered = new Date().toISOString();
      alert.triggerPrice = price;
      triggered.push({ alert: alert.id, ...execution });

      // Also place order on Alpaca if connected
      if (alpaca.isConnected()) {
        try {
          const alpacaOrder = await alpaca.placeOrder({
            symbol: alert.symbol,
            assetClass: alert.assetClass || 'crypto',
            qty: quantity.toFixed(8),
            side: alert.action,
            type: 'market',
            stopLoss: stopLoss,
            takeProfit: takeProfit,
          });
          execution.alpacaOrderId = alpacaOrder.id;
          execution.alpacaStatus = alpacaOrder.status;
        } catch (alpacaErr) {
          console.error(`[Alerts] Alpaca order failed: ${alpacaErr.message}`);
          execution.alpacaError = alpacaErr.message;
        }
      }
    }
  }

  saveAlerts(alerts);
  return { message: 'Monitor complete', triggered, alertsChecked: alerts.length };
}

/**
 * Add a new alert rule.
 */
export function addAlert(rule) {
  const alerts = loadAlerts();
  const id = rule.id || `${rule.symbol.toLowerCase()}_${Date.now()}`;
  alerts.push({
    id,
    symbol: rule.symbol.toUpperCase(),
    assetClass: rule.assetClass || 'crypto',
    condition: rule.condition || 'gte',
    value: rule.value,
    action: rule.action || 'buy',
    message: rule.message || '',
    riskPerTrade: rule.riskPerTrade,
    stopLossPct: rule.stopLossPct,
    riskRewardRatio: rule.riskRewardRatio,
    repeatable: rule.repeatable || false,
    triggered: false,
    createdAt: new Date().toISOString(),
  });
  saveAlerts(alerts);
  return { id, message: `Alert '${id}' added` };
}

/**
 * Remove an alert rule.
 */
export function removeAlert(id) {
  const alerts = loadAlerts();
  const idx = alerts.findIndex(a => a.id === id);
  if (idx === -1) return { error: 'Alert not found' };
  alerts.splice(idx, 1);
  saveAlerts(alerts);
  return { message: `Alert '${id}' removed` };
}

export default { runAlertMonitor, addAlert, removeAlert };
