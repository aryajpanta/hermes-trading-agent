/**
 * Strategy Optimizer
 * Implements one-variable-at-a-time optimization (scientific method).
 * Changes one parameter, deploys the update, and evaluates the outcome.
 */
import fs from 'fs';
import path from 'path';
import YAML from 'yaml';
import store from '../data/store.js';
import getConfig from '../config/index.js';

const config = getConfig();
const STRATEGY_PATH = config.strategy?.strategyConfigPath ||
  path.join(config.dataDir, 'strategy/config.yaml');

/**
 * Get current strategy config as an object.
 */
export function loadStrategy() {
  try {
    const raw = fs.readFileSync(STRATEGY_PATH, 'utf-8');
    return YAML.parse(raw);
  } catch {
    return null;
  }
}

/**
 * Save strategy config.
 */
export function saveStrategy(strategy) {
  const yaml = YAML.stringify(strategy, { indent: 2 });
  fs.writeFileSync(STRATEGY_PATH, yaml);
  store.write('strategy/current', strategy);
  return strategy;
}

/**
 * The optimization parameter space — what we can tweak.
 */
const OPTIMIZABLE_PARAMS = {
  rsiPeriod: { min: 5, max: 30, step: 1, description: 'RSI calculation period' },
  rsiOversold: { min: 15, max: 45, step: 5, description: 'RSI oversold threshold' },
  rsiOverbought: { min: 55, max: 85, step: 5, description: 'RSI overbought threshold' },
  signalThreshold: { min: 10, max: 60, step: 5, description: 'Minimum signal score to trigger trade' },
  riskPerTrade: { min: 0.005, max: 0.05, step: 0.005, description: 'Risk per trade (% of balance)' },
  stopLossPct: { min: 0.01, max: 0.05, step: 0.005, description: 'Stop loss percentage' },
  riskRewardRatio: { min: 1.0, max: 4.0, step: 0.5, description: 'Risk-reward ratio target' },
  macdFast: { min: 6, max: 20, step: 2, description: 'MACD fast EMA period' },
  macdSlow: { min: 20, max: 40, step: 2, description: 'MACD slow EMA period' },
  macdSignal: { min: 5, max: 15, step: 2, description: 'MACD signal line period' },
  bbPeriod: { min: 10, max: 30, step: 2, description: 'Bollinger Band period' },
  bbStdDev: { min: 1.5, max: 3.0, step: 0.25, description: 'Bollinger Band standard deviations' },
  // Weights
  'weights.smaCrossover': { min: 5, max: 30, step: 5, description: 'SMA crossover signal weight' },
  'weights.macdCrossover': { min: 10, max: 40, step: 5, description: 'MACD crossover signal weight' },
  'weights.rsiOversold': { min: 5, max: 30, step: 5, description: 'RSI oversold signal weight' },
  'weights.rsiOverbought': { min: 5, max: 30, step: 5, description: 'RSI overbought signal weight' },
};

/**
 * Get the current state of a nested parameter using dot notation.
 */
function getNested(obj, path) {
  return path.split('.').reduce((current, key) => current?.[key], obj);
}

function setNested(obj, path, value) {
  const keys = path.split('.');
  let current = obj;
  for (let i = 0; i < keys.length - 1; i++) {
    if (!current[keys[i]]) current[keys[i]] = {};
    current = current[keys[i]];
  }
  current[keys[keys.length - 1]] = value;
}

/**
 * Propose an optimization — what parameter to change and in which direction.
 * Based on the latest review's hypotheses.
 */
export function proposeOptimization(review) {
  const strategy = loadStrategy();
  if (!strategy) return { error: 'No strategy config found' };

  const hypotheses = review?.hypotheses || [];
  const previousOpts = store.read('optimizations') || [];

  // Pick the highest severity hypothesis that has specific variables
  const priorityOrder = { critical: 0, high: 1, medium: 2, low: 3 };
  const sorted = [...hypotheses].sort((a, b) => (priorityOrder[a.severity] || 99) - (priorityOrder[b.severity] || 99));

  for (const h of sorted) {
    if (!h.variables || h.variables.length === 0) continue;
    if (h.variables[0] === '*') {
      return {
        type: 'reset',
        description: 'Reset all optimizable parameters to defaults',
        hypothesis: h.hypothesis,
        severity: h.severity,
      };
    }

    const param = h.variables[0];
    const meta = OPTIMIZABLE_PARAMS[param];
    if (!meta) continue;

    const currentValue = getNested(strategy, param);
    if (currentValue === undefined) continue;

    // Check if we've already tried this parameter recently
    const recentOpts = previousOpts.slice(-5);
    const alreadyTried = recentOpts.some(o => o.parameter === param);
    if (alreadyTried) continue;

    // Determine direction based on hypothesis context
    let direction;
    if (h.hypothesis.toLowerCase().includes('tighten') || h.hypothesis.toLowerCase().includes('reduce')) {
      direction = -1;
    } else if (h.hypothesis.toLowerCase().includes('increase') || h.hypothesis.toLowerCase().includes('raise')) {
      direction = 1;
    } else {
      direction = null; // Let optimizer decide
    }

    const newValue = direction !== null
      ? Math.round((currentValue + direction * meta.step) * 1000) / 1000
      : currentValue;

    // Clamp to valid range
    const clamped = Math.max(meta.min, Math.min(meta.max, newValue));

    return {
      type: 'param_change',
      parameter: param,
      currentValue,
      proposedValue: clamped,
      direction: clamped > currentValue ? 'increase' : clamped < currentValue ? 'decrease' : 'unchanged',
      hypothesis: h.hypothesis,
      severity: h.severity,
      meta,
    };
  }

  // If nothing to optimize, propose a random minor tweak
  return {
    type: 'exploratory',
    description: 'No clear optimization target — exploring minor random tweak',
    hypothesis: 'Exploratory: testing if any parameter adjustment improves performance',
    severity: 'low',
  };
}

/**
 * Apply an optimization to the strategy config.
 */
export function applyOptimization(optimization) {
  const strategy = loadStrategy();
  if (!strategy) return { error: 'No strategy config found' };

  const optRecord = {
    ...optimization,
    appliedAt: new Date().toISOString(),
    baselineRef: store.read('reviews/latest')?.cycle || 0,
  };

  if (optimization.type === 'reset') {
    // Could reset specific params to defaults
    optRecord.applied = true;
  } else if (optimization.type === 'param_change' && optimization.proposedValue !== undefined) {
    setNested(strategy, optimization.parameter, optimization.proposedValue);
    saveStrategy(strategy);
    optRecord.applied = true;
  } else if (optimization.type === 'exploratory') {
    // Pick a random under-explored parameter and nudge it
    const allParams = Object.keys(OPTIMIZABLE_PARAMS);
    const previousOpts = store.read('optimizations') || [];
    const triedParams = new Set(previousOpts.map(o => o.parameter));
    const untried = allParams.filter(p => !triedParams.has(p));

    const target = untried.length > 0 ? untried[0] : allParams[Math.floor(Math.random() * allParams.length)];
    const meta = OPTIMIZABLE_PARAMS[target];
    const currentValue = getNested(strategy, target);

    if (currentValue !== undefined) {
      const adjustment = meta.step * (Math.random() > 0.5 ? 1 : -1);
      const newValue = Math.max(meta.min, Math.min(meta.max, Math.round((currentValue + adjustment) * 1000) / 1000));
      setNested(strategy, target, newValue);
      saveStrategy(strategy);
      optRecord.parameter = target;
      optRecord.currentValue = currentValue;
      optRecord.proposedValue = newValue;
      optRecord.applied = true;
    }
  }

  // Log optimization
  const optimizations = store.read('optimizations') || [];
  optimizations.push(optRecord);
  store.write('optimizations', optimizations);

  return optRecord;
}

/**
 * Full optimization cycle: review → propose → apply.
 */
export async function runOptimizationCycle() {
  // Run review first
  const { default: reviewer } = await import('./reviewer.js');
  const review = await reviewer.runReview();

  // Then propose optimization based on review
  const proposal = proposeOptimization(review);

  // Apply it
  const result = applyOptimization(proposal);

  return {
    review,
    proposal,
    result,
  };
}

export default {
  loadStrategy,
  saveStrategy,
  proposeOptimization,
  applyOptimization,
  runOptimizationCycle,
  OPTIMIZABLE_PARAMS,
};
