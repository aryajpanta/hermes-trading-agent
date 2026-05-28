# Hermes Self-Improving Trading Agent

## Overview
Multi-asset paper trading agent deployed 24/7 on Railway at https://hermes-trading-agent-production-890e.up.railway.app. Uses Hermes Agent's weekly review cycle for self-improvement (one-variable-at-a-time optimization). Accepts TradingView webhook alerts and executes paper trades with full risk management.

## Architecture
- **Backend**: Node.js Express server (src/index.js, port 8080)
- **Strategy Engine**: Technical indicators (SMA crossover, MACD, RSI, Bollinger Bands) with configurable weights
- **Paper Trading**: $100k simulated balance, stop-loss (2%), take-profit (4%), position sizing (1.5% risk)
- **Analytics**: Sharpe ratio, win rate, profit factor, max drawdown, trade quality scoring
- **Self-Improvement**: Hermes cron job (Sundays 9AM) reviews trades, generates hypotheses, optimizes one parameter at a time
- **Hosting**: Railway with Docker, auto-healthcheck, auto-restart

## Tracked Assets
| Symbol | Class | Weight |
|--------|-------|--------|
| BTC | crypto | 25% |
| ETH | crypto | 20% |
| SOL | crypto | 15% |
| AAPL | stock | 15% |
| SPY | stock | 15% |
| EURUSD | forex | 10% |

## Strategy Goals
- Min Sharpe Ratio: 1.5
- Max Drawdown: 15%
- Target 30-day Return: 10%
- Min Win Rate: 45%

## Self-Improvement System
Uses scientific method approach — changes exactly one variable per cycle. First cycle is read-only (review only). After user approval, auto-optimizes: RSI periods, MACD parameters, signal thresholds, risk percentages, indicator weights, and more.

## TradingView Integration
Webhook endpoint: POST /webhook/tradingview with JSON payload containing symbol, action (buy/sell), price, assetClass, and webhook secret.

## Project Location
/Users/aryaj/Desktop/Trading/ — full Node.js project with Dockerfile, Railway config, YAML strategy config.
