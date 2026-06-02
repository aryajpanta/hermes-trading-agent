/**
 * Alpaca Crypto Bracket Monitor
 * Periodically checks local crypto brackets (stop-loss / take-profit)
 * and executes market orders if they are breached.
 */
import store from '../data/store.js';
import { fetchPrice } from '../data/market.js';
import * as alpaca from './alpaca.js';

/**
 * Check all active local crypto brackets against current prices.
 */
export async function checkCryptoBrackets() {
  if (!alpaca.isConnected()) {
    return { status: 'offline', checked: 0, triggered: [] };
  }

  const brackets = store.read('alpaca/crypto_brackets') || {};
  const activeKeys = Object.keys(brackets);

  if (activeKeys.length === 0) {
    return { status: 'idle', checked: 0, triggered: [] };
  }

  let positions = [];
  try {
    positions = await alpaca.getPositions();
  } catch (err) {
    console.error(`[BracketMonitor] Failed to fetch Alpaca positions: ${err.message}`);
    return { status: 'error', error: err.message, checked: 0, triggered: [] };
  }

  // Create a map of active positions for quick lookup
  const positionMap = {};
  for (const pos of positions) {
    positionMap[pos.symbol.toUpperCase()] = pos;
  }

  const triggered = [];
  const updatedBrackets = { ...brackets };

  for (const sym of activeKeys) {
    const bracket = brackets[sym];
    const alpacaPos = positionMap[sym] || positionMap[sym.replace('/', '')];

    // If no active long position on Alpaca, clear the bracket
    if (!alpacaPos || alpacaPos.qty <= 0) {
      console.log(`[BracketMonitor] No active position found for ${sym}. Clearing bracket.`);
      delete updatedBrackets[sym];
      continue;
    }

    // Fetch current price
    const currentPrice = await fetchPrice(bracket.symbol, 'crypto');
    if (!currentPrice) {
      console.log(`[BracketMonitor] Could not fetch price for ${sym}`);
      continue;
    }

    let breachReason = null;
    if (bracket.stopLoss && currentPrice <= bracket.stopLoss) {
      breachReason = 'stop_loss';
    } else if (bracket.takeProfit && currentPrice >= bracket.takeProfit) {
      breachReason = 'take_profit';
    }

    if (breachReason) {
      const triggerPrice = currentPrice;
      console.log(`[BracketMonitor] ${sym} breached ${breachReason} at $${triggerPrice.toFixed(2)} (SL: $${bracket.stopLoss}, TP: $${bracket.takeProfit})`);

      try {
        // Place market sell order on Alpaca
        const exitOrder = await alpaca.placeOrder({
          symbol: bracket.symbol,
          qty: alpacaPos.qty,
          side: 'sell',
          type: 'market',
          assetClass: 'crypto',
        });

        console.log(`[BracketMonitor] Exit order placed for ${sym}. Order ID: ${exitOrder.id}`);
        triggered.push({
          symbol: sym,
          reason: breachReason,
          triggerPrice,
          orderId: exitOrder.id,
        });

        // Clear local bracket
        delete updatedBrackets[sym];
      } catch (err) {
        console.error(`[BracketMonitor] Failed to execute exit order for ${sym}: ${err.message}`);
      }
    }
  }

  // Save changes
  store.write('alpaca/crypto_brackets', updatedBrackets);

  return { status: 'complete', checked: activeKeys.length, triggered };
}

export default { checkCryptoBrackets };
