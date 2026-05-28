#!/bin/bash
# ============================================================
# Hermes Trading Agent — Deployment Script
# ============================================================
# This script deploys the trading agent to Railway 24/7.
# Usage: ./scripts/deploy.sh [--prod]
# ============================================================

set -euo pipefail

DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$DIR"

echo "═══ Hermes Trading Agent — Deployment ═══"
echo ""

# Check Railway CLI
if ! command -v railway &> /dev/null; then
  echo "❌ Railway CLI not found. Install: npm install -g @railway/cli"
  exit 1
fi

# Check if linked to a Railway project
if ! railway status &>/dev/null; then
  echo "📡 Not linked to any Railway project."
  echo "   Linking to 'hermes-trading-agent'..."

  # Try to link or create
  railway link hermes-trading-agent 2>/dev/null || {
    echo "   Creating new project..."
    railway init --name hermes-trading-agent
  }
fi

# Prompt for webhook secret if not set
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "⚠️  Edit .env and set your WEBHOOK_SECRET before deploying!"
  fi
fi

echo ""
echo "📦 Deploying to Railway..."
echo ""

if [ "${1:-}" = "--prod" ]; then
  railway up --environment production
else
  railway up
fi

echo ""
echo "✅ Deployment complete!"
echo ""
echo "   Your agent is now running 24/7 on Railway."
echo "   Run 'railway domain' to get your public URL."
echo "   Configure TradingView alerts to POST to:"
echo "     https://your-app.railway.app/webhook/tradingview"
echo ""

# Show status
railway status
