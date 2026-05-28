#!/bin/bash
# ============================================================
# Review Trades — Hermes Cron Job Entrypoint
# ============================================================
# This is called by Hermes Agent on schedule (weekly).
# It runs the review, optimization, and generates a report.
# ============================================================

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "═══════════════════════════════════════════"
echo "  Hermes Trading Agent — Review Cycle"
echo "  $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "═══════════════════════════════════════════"
echo ""

# Run the review
echo "📊 Running performance review..."
node src/self-improve/reviewer.js 2>&1 || {
  echo "⚠️ Review failed — will retry next cycle"
  exit 1
}

# Run the optimization
echo ""
echo "🔧 Running optimization cycle..."
node src/self-improve/optimizer.js 2>&1 || {
  echo "⚠️ Optimization cycle had issues"
}

# Show latest stats
echo ""
echo "📈 Current status:"
curl -s http://localhost:8080/api/status 2>/dev/null | python3 -m json.tool 2>/dev/null || {
  echo "  (server not reachable — check Railway deployment)"
}

echo ""
echo "✅ Review cycle complete"
echo "═══════════════════════════════════════════"
