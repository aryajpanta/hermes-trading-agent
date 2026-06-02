/**
 * Market Data Fetcher
 * Multi-source: Yahoo Finance (stocks), Binance (crypto), ExchangeRate (forex)
 */
import fetch from 'node-fetch';
import getConfig from '../config/index.js';

const config = getConfig();

const ASSET_CACHE = {};

export async function fetchPrice(symbol, assetClass = 'crypto') {
  const cacheKey = `${symbol}_${assetClass}`;
  if (ASSET_CACHE[cacheKey] && Date.now() - ASSET_CACHE[cacheKey].ts < 60_000) {
    return ASSET_CACHE[cacheKey].price;
  }

  let price;
  try {
    switch (assetClass.toLowerCase()) {
      case 'crypto':
        price = await fetchCryptoPrice(symbol);
        break;
      case 'stock':
        price = await fetchStockPrice(symbol);
        break;
      case 'forex':
        price = await fetchForexPrice(symbol);
        break;
      default:
        price = await fetchCryptoPrice(symbol);
    }
    if (price && price > 0) {
      ASSET_CACHE[cacheKey] = { price, ts: Date.now() };
    }
    return price;
  } catch (err) {
    console.error(`[Market] Error fetching ${symbol} (${assetClass}): ${err.message}`);
    return null;
  }
}

/**
 * Fetch price plus real 24h change percent for a symbol.
 * Returns { price, change24h } — change24h may be null if unavailable.
 */
export async function fetchQuote(symbol, assetClass = 'crypto') {
  try {
    switch (assetClass.toLowerCase()) {
      case 'crypto': return await fetchCryptoQuote(symbol);
      case 'stock':
      case 'forex': return await fetchYahooQuote(symbol, assetClass);
      default:      return await fetchCryptoQuote(symbol);
    }
  } catch (err) {
    console.error(`[Market] Quote error ${symbol} (${assetClass}): ${err.message}`);
    return { price: await fetchPrice(symbol, assetClass), change24h: null };
  }
}

async function fetchCryptoQuote(symbol) {
  const normalized = symbol.toUpperCase().replace('USDT', '').replace('USD', '');
  const id = normalized === 'BTC' ? 'bitcoin' :
             normalized === 'ETH' ? 'ethereum' :
             normalized === 'SOL' ? 'solana' : null;
  if (id) {
    const url = `https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd&include_24hr_change=true`;
    const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
    if (res.ok) {
      const data = await res.json();
      const d = data?.[id];
      if (d?.usd) return { price: d.usd, change24h: d.usd_24h_change ?? null };
    }
  }
  // Fallback: MEXC 24h ticker (price + percent change)
  const url = `https://api.mexc.com/api/v3/ticker/24hr?symbol=${normalized}USDT`;
  const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
  if (!res.ok) return { price: null, change24h: null };
  const data = await res.json();
  return {
    price: parseFloat(data.lastPrice) || null,
    change24h: data.priceChangePercent != null ? parseFloat(data.priceChangePercent) : null,
  };
}

async function fetchYahooQuote(symbol, assetClass) {
  const sym = assetClass === 'forex'
    ? `${encodeURIComponent(symbol)}%3DX`
    : encodeURIComponent(symbol);
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${sym}`;
  try {
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    if (res.ok) {
      const data = await res.json();
      const meta = data?.chart?.result?.[0]?.meta;
      const price = meta?.regularMarketPrice ?? meta?.previousClose ?? null;
      const prev = meta?.chartPreviousClose ?? meta?.previousClose ?? null;
      const change24h = price != null && prev ? ((price - prev) / prev) * 100 : null;
      if (price != null) return { price, change24h };
    }
  } catch {}
  // Forex fallback: Frankfurter (ECB)
  if (assetClass === 'forex') return await fetchFrankfurterQuote(symbol);
  return { price: null, change24h: null };
}

async function fetchCryptoPrice(symbol) {
  const normalized = symbol.toUpperCase().replace('USD', '').replace('USDT', '');
  // Try CoinGecko (no location restrictions, free, no API key needed)
  const id = normalized === 'BTC' ? 'bitcoin' : 
             normalized === 'ETH' ? 'ethereum' :
             normalized === 'SOL' ? 'solana' : null;
  if (id) {
    const url = `https://api.coingecko.com/api/v3/simple/price?ids=${id}&vs_currencies=usd`;
    const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
    if (res.ok) {
      const data = await res.json();
      return data?.[id]?.usd || null;
    }
  }
  // Fallback: MEXC (free, Binance-compatible, no geo blocks)
  const url = `https://api.mexc.com/api/v3/ticker/price?symbol=${normalized}USDT`;
  const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
  if (!res.ok) throw new Error(`Price API responded ${res.status}`);
  const data = await res.json();
  return parseFloat(data.price);
}

async function fetchStockPrice(symbol) {
  // Yahoo Finance via public API
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}`;
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0' }
  });
  if (!res.ok) throw new Error(`Yahoo Finance responded ${res.status}`);
  const data = await res.json();
  const meta = data?.chart?.result?.[0]?.meta;
  return meta?.regularMarketPrice || meta?.previousClose || null;
}

// Split a forex pair like "EURUSD" / "EUR/USD" / "EURUSD=X" into base/quote.
function parseForexPair(pair) {
  const clean = pair.toUpperCase().replace('/', '').replace('=X', '');
  if (clean.length >= 6) return { from: clean.slice(0, 3), to: clean.slice(3, 6) };
  return { from: clean, to: 'USD' };
}

// Fallback forex source: Frankfurter (ECB reference rates, free, no API key).
// Uses an open-ended timeseries so we get the latest rate plus the prior day
// for a real 24h change. Only covers business days / major currencies.
async function fetchFrankfurterQuote(pair) {
  const { from, to } = parseForexPair(pair);
  const start = new Date(Date.now() - 10 * 86_400_000).toISOString().slice(0, 10);
  const url = `https://api.frankfurter.dev/v1/${start}..?from=${from}&to=${to}`;
  const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
  if (!res.ok) return { price: null, change24h: null };
  const data = await res.json();
  const dates = Object.keys(data.rates || {}).sort();
  if (dates.length === 0) return { price: null, change24h: null };
  const price = data.rates[dates[dates.length - 1]]?.[to] ?? null;
  const prev = dates.length > 1 ? data.rates[dates[dates.length - 2]]?.[to] : null;
  const change24h = price != null && prev ? ((price - prev) / prev) * 100 : null;
  return { price, change24h };
}

async function fetchFrankfurterOHLCV(pair, days) {
  const { from, to } = parseForexPair(pair);
  const start = new Date(Date.now() - (days + 5) * 86_400_000).toISOString().slice(0, 10);
  const url = `https://api.frankfurter.dev/v1/${start}..?from=${from}&to=${to}`;
  const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
  if (!res.ok) return [];
  const data = await res.json();
  return Object.keys(data.rates || {}).sort().map(d => {
    const rate = data.rates[d]?.[to];
    if (rate == null) return null;
    // ECB publishes a single daily reference rate — close-only candles.
    return { timestamp: new Date(d + 'T00:00:00Z').getTime(), open: rate, high: rate, low: rate, close: rate, volume: 0 };
  }).filter(Boolean);
}

async function fetchForexPrice(pair) {
  // Primary: Yahoo Finance forex pairs with =X suffix
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(pair)}%3DX`;
  try {
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    if (res.ok) {
      const data = await res.json();
      const meta = data?.chart?.result?.[0]?.meta;
      const price = meta?.regularMarketPrice || meta?.previousClose || null;
      if (price) return price;
    }
  } catch {}
  // Fallback: Frankfurter (ECB)
  const { price } = await fetchFrankfurterQuote(pair);
  return price;
}

export async function fetchHistoricalData(symbol, assetClass = 'crypto', days = 30) {
  try {
    switch (assetClass.toLowerCase()) {
      case 'crypto':
        return await fetchCryptoOHLCV(symbol, days);
      case 'stock':
        return await fetchStockOHLCV(symbol, days);
      case 'forex':
        return await fetchForexOHLCV(symbol, days);
      default:
        return [];
    }
  } catch (err) {
    console.error(`[Market] Error fetching history for ${symbol}: ${err.message}`);
    return [];
  }
}

async function fetchCryptoOHLCV(symbol, days) {
  const normalized = symbol.toUpperCase().replace('USD', '').replace('USDT', '');
  const interval = days <= 2 ? '1h' : days <= 14 ? '4h' : '1d';
  const limit = Math.min(days, 365);
  // Use MEXC (free, no API key needed, Binance-compatible format, no geo blocks)
  const url = `https://api.mexc.com/api/v3/klines?symbol=${normalized}USDT&interval=${interval}&limit=${limit}`;
  try {
    const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
    if (res.ok) {
      const data = await res.json();
      return data.map(k => ({
        timestamp: k[0],
        open: parseFloat(k[1]),
        high: parseFloat(k[2]),
        low: parseFloat(k[3]),
        close: parseFloat(k[4]),
        volume: parseFloat(k[5]),
      }));
    }
  } catch {}
  return [];
}

async function fetchStockOHLCV(symbol, days) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?range=${days}d&interval=1d`;
  const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
  if (!res.ok) throw new Error(`Yahoo chart responded ${res.status}`);
  const data = await res.json();
  const result = data?.chart?.result?.[0];
  if (!result) return [];
  const timestamps = result.timestamp || [];
  const quote = result.indicators?.quote?.[0] || {};
  return timestamps.map((ts, i) => ({
    timestamp: ts * 1000,
    open: quote.open?.[i],
    high: quote.high?.[i],
    low: quote.low?.[i],
    close: quote.close?.[i],
    volume: quote.volume?.[i],
  })).filter(c => c.close != null);
}

async function fetchForexOHLCV(pair, days) {
  // Primary: Yahoo Finance forex pairs with =X suffix
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(pair)}%3DX?range=${days}d&interval=1d`;
  try {
    const res = await fetch(url, { headers: { 'User-Agent': 'Mozilla/5.0' } });
    if (res.ok) {
      const data = await res.json();
      const result = data?.chart?.result?.[0];
      const timestamps = result?.timestamp || [];
      const quote = result?.indicators?.quote?.[0] || {};
      const candles = timestamps.map((ts, i) => ({
        timestamp: ts * 1000,
        open: quote.open?.[i],
        high: quote.high?.[i],
        low: quote.low?.[i],
        close: quote.close?.[i],
        volume: quote.volume?.[i] || 0,
      })).filter(c => c.close != null);
      if (candles.length) return candles;
    }
  } catch {}
  // Fallback: Frankfurter (ECB) close-only daily candles
  return await fetchFrankfurterOHLCV(pair, days);
}

export default { fetchPrice, fetchQuote, fetchHistoricalData };
