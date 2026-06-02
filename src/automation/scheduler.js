/**
 * Automation Scheduler
 * Runs the alert monitor on a short interval and the review/optimization
 * cycle once a day. Both loops are guarded against overlapping runs and can
 * be disabled via the ENABLE_AUTOMATION env var.
 */
import { runAlertMonitor } from '../alerts/monitor.js';
import { runOptimizationCycle } from '../self-improve/optimizer.js';
import store from '../data/store.js';

const MONITOR_INTERVAL_MS = parseInt(process.env.AUTOMATION_INTERVAL_MS || '60000', 10);
const REVIEW_INTERVAL_MS = parseInt(process.env.REVIEW_INTERVAL_MS || String(24 * 60 * 60 * 1000), 10);

const status = {
  enabled: false,
  monitor: { running: false, lastRun: null, lastResult: null, lastError: null, runs: 0, intervalMs: MONITOR_INTERVAL_MS },
  review: { running: false, lastRun: null, lastResult: null, lastError: null, runs: 0, intervalMs: REVIEW_INTERVAL_MS },
};

let monitorTimer = null;
let reviewTimer = null;

async function runMonitorOnce() {
  if (status.monitor.running) return; // overlap guard
  status.monitor.running = true;
  try {
    const r = await runAlertMonitor();
    status.monitor.lastResult = {
      triggered: r.triggered?.length || 0,
      alertsChecked: r.alertsChecked || 0,
    };
    status.monitor.lastError = null;
    if (r.triggered?.length) {
      console.log(`[Automation] Monitor fired ${r.triggered.length} alert(s)`);
    }
  } catch (err) {
    status.monitor.lastError = err.message;
    console.error(`[Automation] Monitor error: ${err.message}`);
  } finally {
    status.monitor.running = false;
    status.monitor.lastRun = new Date().toISOString();
    status.monitor.runs++;
  }
}

async function runReviewOnce() {
  if (status.review.running) return; // overlap guard
  status.review.running = true;
  try {
    const r = await runOptimizationCycle();
    const applied = r.result?.applied;
    status.review.lastResult = {
      cycle: r.review?.cycle,
      applied,
      parameter: r.result?.parameter,
      proposedValue: r.result?.proposedValue,
    };
    status.review.lastError = null;

    // Log to the cycles store so the dashboard reflects self-improvement activity.
    store.append('cycles', {
      timestamp: new Date().toISOString(),
      type: 'review',
      reviewCycle: r.review?.cycle,
      applied,
      parameter: r.result?.parameter,
      proposedValue: r.result?.proposedValue,
      winRate: r.review?.performance?.winRate,
      sharpeRatio: r.review?.performance?.sharpeRatio,
    });
    console.log(`[Automation] Review cycle ${r.review?.cycle} complete (applied: ${applied})`);
  } catch (err) {
    status.review.lastError = err.message;
    console.error(`[Automation] Review error: ${err.message}`);
  } finally {
    status.review.running = false;
    status.review.lastRun = new Date().toISOString();
    status.review.runs++;
  }
}

export function startAutomation() {
  const enabled = process.env.ENABLE_AUTOMATION !== 'false'; // default ON
  status.enabled = enabled;
  if (!enabled) {
    console.log('[Automation] Disabled (ENABLE_AUTOMATION=false)');
    return status;
  }

  // Let the server settle before the first monitor run.
  setTimeout(runMonitorOnce, 10_000);
  monitorTimer = setInterval(runMonitorOnce, MONITOR_INTERVAL_MS);
  reviewTimer = setInterval(runReviewOnce, REVIEW_INTERVAL_MS);

  console.log(`[Automation] Started — monitor every ${Math.round(MONITOR_INTERVAL_MS / 1000)}s, review every ${Math.round(REVIEW_INTERVAL_MS / 3600000)}h`);
  return status;
}

export function stopAutomation() {
  if (monitorTimer) clearInterval(monitorTimer);
  if (reviewTimer) clearInterval(reviewTimer);
  monitorTimer = reviewTimer = null;
  status.enabled = false;
}

export function getAutomationStatus() {
  return status;
}

export default { startAutomation, stopAutomation, getAutomationStatus };
