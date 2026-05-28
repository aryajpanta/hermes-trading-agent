/**
 * Technical Indicators
 * Used by the strategy engine for generating signals.
 * These are kept simple and transparent so Hermes can review/improve them.
 */

export function sma(data, period) {
  const result = [];
  for (let i = 0; i < data.length; i++) {
    if (i < period - 1) {
      result.push(null);
    } else {
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sum += data[j];
      }
      result.push(sum / period);
    }
  }
  return result;
}

export function ema(data, period) {
  const result = [];
  const multiplier = 2 / (period + 1);
  for (let i = 0; i < data.length; i++) {
    if (i === 0) {
      result.push(data[i]);
    } else if (i < period - 1) {
      result.push(null);
    } else if (i === period - 1) {
      let sum = 0;
      for (let j = 0; j < period; j++) sum += data[j];
      result.push(sum / period);
    } else {
      result.push((data[i] - result[i - 1]) * multiplier + result[i - 1]);
    }
  }
  return result;
}

export function rsi(data, period = 14) {
  const result = [];
  const gains = [];
  const losses = [];
  for (let i = 1; i < data.length; i++) {
    const diff = data[i] - data[i - 1];
    gains.push(diff > 0 ? diff : 0);
    losses.push(diff < 0 ? -diff : 0);
  }
  for (let i = 0; i < data.length; i++) {
    if (i < period) {
      result.push(null);
    } else {
      const avgGain = gains.slice(i - period, i).reduce((a, b) => a + b, 0) / period;
      const avgLoss = losses.slice(i - period, i).reduce((a, b) => a + b, 0) / period;
      if (avgLoss === 0) {
        result.push(100);
      } else {
        const rs = avgGain / avgLoss;
        result.push(100 - (100 / (1 + rs)));
      }
    }
  }
  return result;
}

export function macd(data, fastPeriod = 12, slowPeriod = 26, signalPeriod = 9) {
  const fastEma = ema(data, fastPeriod);
  const slowEma = ema(data, slowPeriod);
  const macdLine = [];
  for (let i = 0; i < data.length; i++) {
    if (fastEma[i] === null || slowEma[i] === null) {
      macdLine.push(null);
    } else {
      macdLine.push(fastEma[i] - slowEma[i]);
    }
  }
  // Filter out nulls for signal line calculation
  const validMacd = macdLine.filter(v => v !== null);
  const signalRaw = ema(validMacd, signalPeriod);
  const signal = [];
  let validIdx = 0;
  for (let i = 0; i < data.length; i++) {
    if (macdLine[i] === null) {
      signal.push(null);
    } else {
      signal.push(signalRaw[validIdx]);
      validIdx++;
    }
  }
  const histogram = macdLine.map((v, i) => v !== null && signal[i] !== null ? v - signal[i] : null);
  return { macdLine, signal, histogram };
}

export function bollingerBands(data, period = 20, stdDev = 2) {
  const middle = sma(data, period);
  const upper = [];
  const lower = [];
  for (let i = 0; i < data.length; i++) {
    if (middle[i] === null) {
      upper.push(null);
      lower.push(null);
    } else {
      let sumSq = 0;
      for (let j = i - period + 1; j <= i; j++) {
        sumSq += (data[j] - middle[i]) ** 2;
      }
      const std = Math.sqrt(sumSq / period);
      upper.push(middle[i] + stdDev * std);
      lower.push(middle[i] - stdDev * std);
    }
  }
  return { upper, middle, lower };
}

export function atr(highs, lows, closes, period = 14) {
  const tr = [];
  for (let i = 0; i < closes.length; i++) {
    if (i === 0) {
      tr.push(highs[i] - lows[i]);
    } else {
      tr.push(Math.max(
        highs[i] - lows[i],
        Math.abs(highs[i] - closes[i - 1]),
        Math.abs(lows[i] - closes[i - 1])
      ));
    }
  }
  return ema(tr, period);
}

export default { sma, ema, rsi, macd, bollingerBands, atr };
