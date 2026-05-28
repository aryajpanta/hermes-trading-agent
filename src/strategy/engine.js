/**
 * Trading Strategy Engine
 * Evaluates market data against strategy rules and generates signals.
 * The strategy parameters are configurable and can be optimized by the self-improvement system.
 */
import { sma, ema, rsi, macd, bollingerBands } from './indicators.js';
import { calcPositionSize, calcStopLoss, calcTakeProfit } from './risk.js';

/**
 * Evaluate a single asset's market data and return a trading signal.
 * @param {Object} candles - Array of OHLCV candles [{timestamp, open, high, low, close, volume}]
 * @param {Object} params - Strategy parameters (loaded from config)
 * @returns {Object} { signal: 'buy'|'sell'|'hold', confidence, entryPrice, stopLoss, takeProfit, reason }
 */
export function evaluate(candles, params) {
  if (!candles || candles.length < 50) {
    return { signal: 'hold', confidence: 0, reason: 'Insufficient data' };
  }

  const closes = candles.map(c => c.close);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);
  const volumes = candles.map(c => c.volume || 0);
  const currentPrice = closes[closes.length - 1];
  const currentVolume = volumes[volumes.length - 1];
  const avgVolume = volumes.slice(-20).reduce((a, b) => a + b, 0) / 20;

  // Calculate indicators
  const rsiValues = rsi(closes, params.rsiPeriod || 14);
  const macdResult = macd(closes, params.macdFast || 12, params.macdSlow || 26, params.macdSignal || 9);
  const bb = bollingerBands(closes, params.bbPeriod || 20, params.bbStdDev || 2);
  const sma20 = sma(closes, 20);
  const sma50 = sma(closes, 50);

  const lastRSI = rsiValues[rsiValues.length - 1];
  const prevRSI = rsiValues[rsiValues.length - 2];
  const lastMACD = macdResult.macdLine[macdResult.macdLine.length - 1];
  const prevMACD = macdResult.macdLine[macdResult.macdLine.length - 2];
  const lastSignal = macdResult.signal[macdResult.signal.length - 1];
  const lastHist = macdResult.histogram[macdResult.histogram.length - 1];
  const prevHist = macdResult.histogram[macdResult.histogram.length - 2];
  const upperBand = bb.upper[bb.upper.length - 1];
  const lowerBand = bb.lower[bb.lower.length - 1];
  const lastSMA20 = sma20[sma20.length - 1];
  const lastSMA50 = sma50[sma50.length - 1];
  const prevSMA20 = sma20[sma20.length - 2];

  let score = 0;
  const reasons = [];

  // --- Trend Following Signals ---

  // SMA crossover
  if (lastSMA20 && lastSMA50 && prevSMA20) {
    if (lastSMA20 > lastSMA50 && prevSMA20 <= lastSMA50) {
      score += params.weights?.smaCrossover || 15;
      reasons.push('SMA20 crossed above SMA50 (bullish)');
    } else if (lastSMA20 < lastSMA50 && prevSMA20 >= lastSMA50) {
      score -= params.weights?.smaCrossover || 15;
      reasons.push('SMA20 crossed below SMA50 (bearish)');
    }
  }

  // Price vs SMA20 trend
  if (lastSMA20) {
    if (currentPrice > lastSMA20) {
      score += params.weights?.priceAboveSMA || 5;
    } else {
      score -= params.weights?.priceAboveSMA || 5;
    }
  }

  // MACD crossover
  if (lastMACD !== null && prevMACD !== null && lastSignal !== null) {
    if (lastMACD > lastSignal && prevMACD <= lastSignal) {
      score += params.weights?.macdCrossover || 20;
      reasons.push('MACD crossed above signal (bullish)');
    } else if (lastMACD < lastSignal && prevMACD >= lastSignal) {
      score -= params.weights?.macdCrossover || 20;
      reasons.push('MACD crossed below signal (bearish)');
    }
    // MACD histogram momentum
    if (lastHist !== null && prevHist !== null) {
      if (lastHist > prevHist) score += params.weights?.macdMomentum || 5;
      else score -= params.weights?.macdMomentum || 5;
    }
  }

  // RSI
  if (lastRSI !== null) {
    if (lastRSI < params.rsiOversold || 30) {
      score += params.weights?.rsiOversold || 15;
      reasons.push(`RSI oversold (${lastRSI.toFixed(1)})`);
    } else if (lastRSI > params.rsiOverbought || 70) {
      score -= params.weights?.rsiOverbought || 15;
      reasons.push(`RSI overbought (${lastRSI.toFixed(1)})`);
    }
    // RSI divergence (simple: compare RSI trend to price trend)
    if (lastRSI > prevRSI && currentPrice < closes[closes.length - 2]) {
      score += params.weights?.rsiDivergence || 10;
      reasons.push('Bullish RSI divergence');
    } else if (lastRSI < prevRSI && currentPrice > closes[closes.length - 2]) {
      score -= params.weights?.rsiDivergence || 10;
      reasons.push('Bearish RSI divergence');
    }
  }

  // Bollinger Bands
  if (upperBand !== null && lowerBand !== null) {
    if (currentPrice <= lowerBand) {
      score += params.weights?.bbOversold || 10;
      reasons.push('Price at lower Bollinger Band');
    } else if (currentPrice >= upperBand) {
      score -= params.weights?.bbOverbought || 10;
      reasons.push('Price at upper Bollinger Band');
    }
  }

  // Volume confirmation
  if (currentVolume > avgVolume * (params.volumeThreshold || 1.5)) {
    if (score > 0) {
      score += params.weights?.volumeConfirmation || 5;
      reasons.push('High volume confirms direction');
    }
  }

  // --- Decision ---
  const threshold = params.signalThreshold || 30;
  let signal = 'hold';
  let confidence = 0;

  if (score >= threshold) {
    signal = 'buy';
    confidence = Math.min(1, score / 100);
  } else if (score <= -threshold) {
    signal = 'sell';
    confidence = Math.min(1, Math.abs(score) / 100);
  }

  // Calculate risk parameters
  const riskPerTrade = params.riskPerTrade || 0.01;
  const stopLossPct = params.stopLossPct || 0.02;
  const riskRewardRatio = params.riskRewardRatio || 2;

  return {
    signal,
    confidence,
    score,
    entryPrice: currentPrice,
    stopLoss: signal !== 'hold' ? calcStopLoss(currentPrice, signal === 'buy' ? 'long' : 'short', stopLossPct) : null,
    takeProfit: signal !== 'hold' ? calcTakeProfit(currentPrice, signal === 'buy' ? 'long' : 'short', riskRewardRatio * stopLossPct) : null,
    reason: reasons.length > 0 ? reasons.join('; ') : 'No clear signal',
    indicators: {
      rsi: lastRSI,
      macd: lastMACD,
      macdSignal: lastSignal,
      bbUpper: upperBand,
      bbLower: lowerBand,
      sma20: lastSMA20,
      sma50: lastSMA50,
    },
    scoreBreakdown: { total: score, components: reasons.length },
  };
}

/**
 * Evaluate multiple assets and return ranked signals.
 */
export function evaluateMulti(marketData, params) {
  const results = [];
  for (const [symbol, data] of Object.entries(marketData)) {
    if (data.candles && data.candles.length > 0) {
      const result = evaluate(data.candles, {
        ...params,
        ...(data.params || {}),
      });
      results.push({ symbol, assetClass: data.assetClass || 'crypto', ...result });
    }
  }
  // Sort by confidence descending
  results.sort((a, b) => Math.abs(b.confidence) - Math.abs(a.confidence));
  return results;
}

export default { evaluate, evaluateMulti };
