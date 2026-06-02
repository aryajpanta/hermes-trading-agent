/**
 * Alpaca Broker Integration
 * Connects the trading agent to Alpaca Markets for live/paper trading.
 *
 * Alpaca provides:
 * - Free paper trading API (same endpoints, different base URL)
 * - Commission-free stock/ETF/crypto trading
 * - REST API for orders, positions, account
 * - Real-time market data via WebSocket
 */
import Alpaca from '@alpacahq/alpaca-trade-api';
import getConfig from '../config/index.js';
import store from '../data/store.js';

let alpaca = null;

/**
 * Initialize the Alpaca client with API credentials.
 */
export function connect(keyId, secretKey, paper = true) {
  alpaca = new Alpaca({
    keyId: keyId,
    secretKey: secretKey,
    paper: paper,  // true = paper trading, false = live
    usePolygon: false, // Don't need Polygon data
  });

  store.write('alpaca/connection', {
    connected: true,
    paper,
    connectedAt: new Date().toISOString(),
    keyPreview: keyId.slice(0, 8) + '...',
  });

  return { connected: true, paper };
}

/**
 * Disconnect Alpaca and revert to local paper trading.
 */
export function disconnect() {
  alpaca = null;
  store.write('alpaca/connection', {
    connected: false,
    paper: true,
    connectedAt: null,
  });
  return { connected: false };
}

/**
 * Check if Alpaca is connected.
 */
export function isConnected() {
  return alpaca !== null;
}

/**
 * Get Alpaca connection status.
 */
export function getStatus() {
  if (!alpaca) {
    return store.read('alpaca/connection') || { connected: false, paper: true };
  }
  return store.read('alpaca/connection') || { connected: true };
}

/**
 * Get account info — buying power, equity, positions.
 */
export async function getAccount() {
  if (!alpaca) throw new Error('Alpaca not connected');
  const account = await alpaca.getAccount();
  return {
    accountNumber: account.account_number,
    status: account.status,
    cash: parseFloat(account.cash),
    portfolioValue: parseFloat(account.portfolio_value),
    buyingPower: parseFloat(account.buying_power),
    dayTradeCount: account.day_trade_count,
    isPaper: account.account_number?.startsWith('PAPER'),
  };
}

/**
 * Place a market order.
 */
// Crypto symbols require "BTC/USD" format; detect by checking for no slash and known crypto-like symbols
function normalizeSymbol(symbol, assetClass) {
  if (assetClass === 'crypto' && !symbol.includes('/')) {
    return `${symbol}/USD`;
  }
  return symbol;
}

export async function placeOrder({ symbol, qty, side, type = 'market', timeInForce, assetClass, limitPrice, stopLoss, takeProfit }) {
  if (!alpaca) throw new Error('Alpaca not connected');

  const isCrypto = assetClass === 'crypto' || symbol.includes('/');
  // Crypto only supports gtc/ioc; equities default to day
  const tif = timeInForce || (isCrypto ? 'gtc' : 'day');
  const normSym = normalizeSymbol(symbol, assetClass);

  const order = {
    symbol: normSym,
    qty: qty,
    side: side,
    type: type,
    time_in_force: tif,
  };

  if (limitPrice) order.limit_price = limitPrice;
  // Bracket orders (stop_loss/take_profit) are not supported for crypto on Alpaca
  if (stopLoss && !isCrypto) {
    order.order_class = 'bracket';
    order.stop_loss = { stop_price: stopLoss };
    if (takeProfit) {
      order.take_profit = { limit_price: takeProfit };
    }
  }

  const result = await alpaca.createOrder(order);

  // If crypto, handle bracket parameters locally
  if (isCrypto) {
    const brackets = store.read('alpaca/crypto_brackets') || {};
    const symKey = normSym.toUpperCase();
    if (side === 'buy' && (stopLoss || takeProfit)) {
      brackets[symKey] = {
        symbol: symKey,
        stopLoss: stopLoss ? parseFloat(stopLoss) : null,
        takeProfit: takeProfit ? parseFloat(takeProfit) : null,
        qty: parseFloat(qty),
        createdAt: new Date().toISOString(),
      };
      store.write('alpaca/crypto_brackets', brackets);
    } else if (side === 'sell') {
      // Clear brackets upon selling
      delete brackets[symKey];
      store.write('alpaca/crypto_brackets', brackets);
    }
  }

  // Log the order
  store.append('alpaca/orders', {
    ...result,
    _timestamp: new Date().toISOString(),
  });

  return {
    id: result.id,
    symbol: result.symbol,
    side: result.side,
    qty: result.qty,
    type: result.type,
    status: result.status,
    createdAt: result.created_at,
    filledQty: result.filled_qty,
    filledAvgPrice: result.filled_avg_price,
  };
}

/**
 * Close all positions.
 */
export async function closeAllPositions() {
  if (!alpaca) throw new Error('Alpaca not connected');
  const result = await alpaca.closeAllPositions();
  return result;
}

/**
 * Get current positions.
 */
export async function getPositions() {
  if (!alpaca) throw new Error('Alpaca not connected');
  const positions = await alpaca.getPositions();
  return positions.map(p => ({
    symbol: p.symbol,
    qty: parseFloat(p.qty),
    avgEntryPrice: parseFloat(p.avg_entry_price),
    currentPrice: parseFloat(p.current_price),
    marketValue: parseFloat(p.market_value),
    unrealizedPnl: parseFloat(p.unrealized_pl),
    unrealizedPnlPercent: parseFloat(p.unrealized_plpc),
    dayPnl: parseFloat(p.unrealized_intraday_pl),
  }));
}

/**
 * Get all orders (recent history).
 */
export async function getOrders(limit = 50, status = 'all') {
  if (!alpaca) throw new Error('Alpaca not connected');
  const orders = await alpaca.getOrders({
    status,
    limit,
    nested: true,
  });
  return orders.map(o => ({
    id: o.id,
    symbol: o.symbol,
    side: o.side,
    qty: o.qty,
    type: o.type,
    status: o.status,
    filledQty: o.filled_qty,
    filledAvgPrice: o.filled_avg_price,
    createdAt: o.created_at,
    updatedAt: o.updated_at,
  }));
}

/**
 * Sync our paper trading state with Alpaca's actual state.
 * This keeps the local portfolio in sync after Alpaca fills orders.
 */
export async function syncPortfolio() {
  if (!alpaca) return null;

  const [account, positions, orders] = await Promise.all([
    getAccount(),
    getPositions(),
    getOrders(5, 'open'),
  ]);

  return { account, positions, openOrders: orders };
}

export default {
  connect,
  disconnect,
  isConnected,
  getStatus,
  getAccount,
  placeOrder,
  closeAllPositions,
  getPositions,
  getOrders,
  syncPortfolio,
};
