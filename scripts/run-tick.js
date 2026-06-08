#!/usr/bin/env node
import { tick } from '../src/papertrading/engine.js';
import getConfig from '../src/config/index.js';

async function main() {
  const config = getConfig();
  console.log(`[${new Date().toISOString()}] Running strategy tick...`);
  try {
    const result = await tick(config.strategy);
    console.log('\n--- Tick Result ---');
    console.log('Open Positions:', result.portfolio?.openPositions);
    console.log('Total Value:', result.portfolio?.totalValue);
    console.log('Signals evaluated:');
    result.signals.forEach(s => {
      console.log(`  - ${s.symbol}: Signal = ${s.signal}, Score = ${s.score}, Confidence = ${s.confidence.toFixed(2)}`);
      if (s.indicators?.sentiment !== undefined) {
        console.log(`    Sentiment = ${s.indicators.sentiment}`);
      }
    });
  } catch (err) {
    console.error('Tick execution failed:', err);
  }
}

main();
