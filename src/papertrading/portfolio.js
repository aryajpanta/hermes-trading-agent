/**
 * Paper Trading Portfolio
 * Tracks balances, open positions, and trade history.
 */
import store from '../data/store.js';

const DEFAULT_BALANCE = 100000;

export function loadPortfolio(initialBalance) {
  let portfolio = store.read('portfolio');
  if (!portfolio) {
    portfolio = {
      balances: { USD: initialBalance || DEFAULT_BALANCE },
      positions: [],
      tradeCount: 0,
      winningTrades: 0,
      losingTrades: 0,
      peakBalance: initialBalance || DEFAULT_BALANCE,
      createdAt: new Date().toISOString(),
    };
    store.write('portfolio', portfolio);
  }
  return portfolio;
}

export function getPortfolio() {
  return store.read('portfolio') || loadPortfolio();
}

export function savePortfolio(portfolio) {
  portfolio.updatedAt = new Date().toISOString();
  const totalValue = getTotalValue(portfolio);
  portfolio.totalValue = totalValue;
  if (totalValue > portfolio.peakBalance) {
    portfolio.peakBalance = totalValue;
  }
  store.write('portfolio', portfolio);
}

export function getTotalValue(portfolio) {
  let total = portfolio.balances?.USD || 0;
  for (const pos of (portfolio.positions || [])) {
    total += pos.currentValue || (pos.quantity * pos.currentPrice);
  }
  return total;
}

export function hasOpenPosition(portfolio, symbol) {
  return portfolio.positions.some(p => p.symbol === symbol && p.status === 'open');
}

export function openPosition(portfolio, { symbol, assetClass, side, quantity, entryPrice, stopLoss, takeProfit, reason }) {
  const cost = quantity * entryPrice;
  const currentBalance = portfolio.balances?.USD || 0;
  if (currentBalance < cost) {
    throw new Error(`Insufficient USD balance to open ${symbol} position. Cost: $${cost.toFixed(2)}, Balance: $${currentBalance.toFixed(2)}`);
  }

  // Deduct cost from cash balance
  portfolio.balances.USD = currentBalance - cost;

  const position = {
    id: `${symbol}_${Date.now()}`,
    symbol,
    assetClass: assetClass || 'crypto',
    side,
    quantity,
    entryPrice,
    currentPrice: entryPrice,
    stopLoss,
    takeProfit,
    status: 'open',
    reason,
    pnl: 0,
    pnlPercent: 0,
    openedAt: new Date().toISOString(),
  };

  portfolio.positions.push(position);
  portfolio.tradeCount++;
  savePortfolio(portfolio);

  // Log the trade
  store.append('trades', {
    type: 'entry',
    ...position,
    balanceAfter: portfolio.balances?.USD,
  });

  return position;
}

export function closePosition(portfolio, positionId, exitPrice, exitReason) {
  const idx = portfolio.positions.findIndex(p => p.id === positionId && p.status === 'open');
  if (idx === -1) return null;

  const position = portfolio.positions[idx];
  const entryValue = position.quantity * position.entryPrice;
  const exitValue = position.quantity * exitPrice;
  const pnl = position.side === 'long' ? exitValue - entryValue : entryValue - exitValue;
  const pnlPercent = (pnl / entryValue) * 100;

  // Update balance
  portfolio.balances.USD = (portfolio.balances.USD || 0) + entryValue + pnl;

  // Record position
  position.status = 'closed';
  position.exitPrice = exitPrice;
  position.pnl = pnl;
  position.pnlPercent = pnlPercent;
  position.exitReason = exitReason;
  position.closedAt = new Date().toISOString();

  if (pnl > 0) portfolio.winningTrades++;
  else if (pnl < 0) portfolio.losingTrades++;

  portfolio.positions[idx] = position;

  // Update total value and peak
  const totalValue = getTotalValue(portfolio);
  if (totalValue > portfolio.peakBalance) {
    portfolio.peakBalance = totalValue;
  }

  savePortfolio(portfolio);

  // Log the trade
  store.append('trades', {
    type: 'exit',
    positionId: position.id,
    symbol: position.symbol,
    side: position.side,
    entryPrice: position.entryPrice,
    exitPrice,
    pnl,
    pnlPercent,
    exitReason,
    holdDuration: position.closedAt - position.openedAt,
    balanceAfter: portfolio.balances?.USD,
  });

  return position;
}

export function updatePositionPrices(portfolio, priceData) {
  for (const [symbol, price] of Object.entries(priceData)) {
    for (const pos of portfolio.positions) {
      if (pos.symbol === symbol && pos.status === 'open') {
        pos.currentPrice = price;
        const entryValue = pos.quantity * pos.entryPrice;
        const currentValue = pos.quantity * price;
        pos.pnl = pos.side === 'long' ? currentValue - entryValue : entryValue - currentValue;
        pos.pnlPercent = (pos.pnl / entryValue) * 100;
        pos.currentValue = currentValue;
      }
    }
  }
  savePortfolio(portfolio);
  return portfolio;
}

export default {
  loadPortfolio,
  getPortfolio,
  savePortfolio,
  getTotalValue,
  hasOpenPosition,
  openPosition,
  closePosition,
  updatePositionPrices,
};
