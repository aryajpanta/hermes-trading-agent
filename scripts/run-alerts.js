#!/usr/bin/env node
/**
 * Alert Monitor Runner — called by cron job
 */
import { runAlertMonitor } from '../src/alerts/monitor.js';

async function main() {
  console.log(`[${new Date().toISOString()}] Running alert monitor...`);
  const result = await runAlertMonitor();
  console.log(JSON.stringify(result, null, 2));
}

main().catch(err => {
  console.error('Alert monitor failed:', err.message);
  process.exit(1);
});
