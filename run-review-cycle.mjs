#!/usr/bin/env node
/**
 * Runs the full review + optimization cycle for the Hermes Trading Agent.
 * Invoked by Hermes Agent's daily cron job.
 */
import { runReview } from './src/self-improve/reviewer.js';
import { runOptimizationCycle } from './src/self-improve/optimizer.js';

async function main() {
  const mode = process.argv[2] || 'full'; // review-only | full

  console.log('=== Hermes Trading Agent Daily Review Cycle ===');
  console.log(`Mode: ${mode}`);
  console.log(`Time: ${new Date().toISOString()}\n`);

  // Step 1: Run the review
  console.log('--- Step 1: Performance Review ---');
  const review = await runReview();
  console.log(`Review cycle: ${review.cycle}`);
  console.log(`Total trades (closed): ${review.performance.totalTrades}`);
  console.log(`Win rate: ${review.performance.winRate}%`);
  console.log(`Sharpe ratio: ${review.performance.sharpeRatio}`);
  console.log(`Total return: ${review.performance.totalReturn}%`);
  console.log(`Max drawdown: ${review.performance.maxDrawdown}%`);
  console.log(`Hypotheses generated: ${review.hypotheses.length}`);
  console.log(`Actions proposed: ${review.actions.length}\n`);

  if (mode === 'review-only') {
    console.log('Review-only mode — skipping optimization.\n');
    process.exit(0);
  }

  // Step 2: Run optimization
  console.log('--- Step 2: Optimization ---');
  try {
    const result = await runOptimizationCycle();
    console.log(`Optimization applied: ${result.result?.applied}`);
    if (result.result?.type === 'param_change') {
      console.log(`Parameter: ${result.result.parameter}`);
      console.log(`Changed: ${result.result.currentValue} → ${result.result.proposedValue}`);
    } else {
      console.log(`Optimization type: ${result.result?.type}`);
    }
    console.log(JSON.stringify(result.result, null, 2));
  } catch (err) {
    console.error('Optimization error:', err.message);
  }
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
