# Spec: Unified Trading System

> Living spec for the merged `trading-intelligence` + `hermes-trading-agent` system. One Python service on Railway.

## Objective

Single Python service that:
- Collects market data from yfinance, CoinGecko, Binance, and AlphaVantage
- Runs 15 strategies from YAML configs
- Uses FinBERT + VADER + optional Gemini AI for sentiment
- Manages paper + live (approval-gated) Alpaca trading
- Runs a continuous 60s tick loop for SL/TP monitoring
- Has a self-improve loop (daily review + parameter optimizer)
- Exposes a FastAPI dashboard + API
- Receives TradingView webhooks
- Posts daily summary to Discord #investing

## Tech Stack

| Component | Library | Purpose |
|-----------|---------|---------|
| API | FastAPI + uvicorn | HTTP server, dashboard, webhooks |
| DB | SQLAlchemy + SQLite (aiosqlite) | Market data, sentiment, settings |
| Data | yfinance, ccxt, requests | Multi-source price + history |
| Broker | alpaca-py | Paper + live trading |
| Sentiment | transformers (FinBERT), vaderSentiment, google-generativeai | News scoring |
| Strategies | ta, ta-lib, pandas, numpy | Indicators + signal logic |
| Backtest | vectorbt | Historical strategy eval |
| Config | pydantic, pyyaml, python-dotenv | Unified config |
| Deploy | Docker (python:3.11-slim) + Railway | Production hosting |

## Project Structure

```
src/
├── alerts/              # Alerts engine (ported from HTA)
├── automation/          # Continuous tick + daily review (ported from HTA)
├── broker/              # Alpaca wrapper
├── data/                # Multi-source collector + storage
│   └── sources/         # yahoo, coingecko, binance, alphavantage
├── decision/            # Signal aggregation, risk, position sizing
├── execution/           # Paper + live executor, emergency stop
├── learning/            # Performance tracking, regime detection
├── sentiment/           # FinBERT + VADER + Gemini
├── strategy/            # 15 strategy implementations + library
├── tradingview/         # Webhook receiver
├── dashboard/           # FastAPI dashboard + API
├── config.py            # Unified env + YAML settings
└── main.py              # Production entry point
```

## Commands

```bash
# Local dev
source .venv/bin/activate
python scripts/trade.py                    # one-shot run
python -m src.dashboard                    # dashboard only on :8000
python -m src.main                         # full app (dashboard + tick loop)

# Tests
pytest tests/ -v --cov=src

# Lint
mypy src/ && flake8 src/

# Docker
docker build -t unified-trading .
docker run -p 8000:8000 --env-file .env unified-trading

# Deploy
git push origin main  # Railway auto-deploys
```

## Endpoints (after merge)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Health check |
| GET | `/` | Dashboard overview |
| GET | `/markets` | Markets detail |
| GET | `/strategies` | Strategies list |
| GET | `/sentiment` | Sentiment analysis |
| GET | `/trades` | Trade history |
| GET | `/settings` | Settings page |
| GET | `/api/status` | System status (HTA-compatible) |
| GET | `/api/portfolio` | Open positions + cash + P&L |
| GET | `/api/trades` | Trade history |
| GET | `/api/cycles` | Automation cycle log |
| GET | `/api/performance` | Win rate, Sharpe, drawdown |
| GET | `/api/prices` | Live prices for watchlist |
| GET | `/api/history` | Historical OHLCV |
| POST | `/api/tick` | Manually trigger a tick |
| POST | `/api/paper/order` | Manual paper order |
| POST | `/api/review` | Manual review trigger |
| POST | `/api/optimize/cycle` | Manual optimize trigger |
| GET | `/api/alpaca/{account,positions,orders,status}` | Real Alpaca proxy |
| POST | `/api/alpaca/{connect,disconnect,order,sync}` | Real Alpaca control |
| GET | `/api/alerts` | List alerts |
| POST | `/api/alerts` | Create alert |
| DELETE | `/api/alerts/{id}` | Remove alert |
| POST | `/webhook/tradingview` | TradingView webhook |
| GET | `/api/tradingview/setup` | Webhook setup guide |

## Boundaries

**Always:**
- Run tests before commits
- Validate env vars on startup
- Log all decisions
- Keep paper mode default

**Ask first:**
- Changing position sizing rules
- Flipping `ALPACA_PAPER=false`
- Modifying emergency stop logic
- Adding new dependencies

**Never:**
- Commit secrets
- Place live orders without explicit approval
- Remove failing tests without fix
- Modify TA-Lib/FinBERT in production without test

## Success Criteria

- [ ] Single Python service on Railway replacing Node service
- [ ] All 4 open positions migrated to new portfolio
- [ ] `/api/status` shows cycles running every ~60s
- [ ] `/api/cycles` log shows daily review completed
- [ ] Discord cron posts to #investing (`1506863196072317049`)
- [ ] Old Node service stopped
- [ ] All existing + new tests pass
- [ ] Alpaca paper account intact

## Open Decisions

_(none — all resolved per Aryaj 2026-06-22)_
