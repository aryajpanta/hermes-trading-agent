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
  // Fallback: Binance
  const url = `https://api.binance.com/api/v3/ticker/price?symbol=${normalized}USDT`;
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

async function fetchForexPrice(pair) {
  // ExchangeRate API (free tier) or fallback
  const normalized = pair.toUpperCase();
  const base = normalized.slice(0, 3);
  const target = normalized.slice(3, 6);

  // Try free exchangerate.host API
  const url = `https://api.exchangerate.host/latest?base=${base}&symbols=${target}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`ExchangeRate responded ${res.status}`);
  const data = await res.json();
  return data?.rates?.[target] || null;
}

export async function fetchHistoricalData(symbol, assetClass = 'crypto', days = 30) {
  try {
    switch (assetClass.toLowerCase()) {
      case 'crypto':
        return await fetchCryptoOHLCV(symbol, days);
      case 'stock':
        return await fetchStockOHLCV(symbol, days);
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
  // Try CoinGecko OHLC (free API)
  const id = normalized === 'BTC' ? 'bitcoin' : 
             normalized === 'ETH' ? 'ethereum' :
             normalized === 'SOL' ? 'solana' : null;
  if (id) {
    const url = `https://api.coingecko.com/api/v3/coins/${id}/ohlc?vs_currency=usd&days=${Math.min(days, 90)}`;
    const res = await fetch(url, { headers: { 'User-Agent': 'HermesTradingAgent/1.0' } });
    if (res.ok) {
      const data = await res.json();
      return data.map(k => ({
        timestamp: k[0],
        open: k[1],
        high: k[2],
        low: k[3],
        close: k[4],
        volume: 0,
      }));
    }
  }
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

export default { fetchPrice, fetchHistoricalData };
