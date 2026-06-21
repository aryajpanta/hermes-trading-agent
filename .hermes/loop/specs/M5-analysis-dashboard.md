# Spec: M5 — Analysis Dashboard

## Objective
A web dashboard showing real-time market state, active signals, strategy performance, and portfolio overview.

## Requirements

### Tech Stack
- **Backend**: FastAPI
- **Frontend**: Jinja2 templates + Alpine.js (lightweight, no React overhead)
- **Charts**: Chart.js or Plotly.js
- **Auth**: Simple API key (local use, not public-facing)

### Dashboard Pages

#### 1. Overview (`/`)
- Market summary (S&P 500, BTC, Gold, DXY)
- Active signals (buy/sell from strategies)
- Portfolio P&L (paper trading)
- Recent trades

#### 2. Markets (`/markets`)
- Price charts with technical indicators
- Volume analysis
- Cross-asset correlation matrix
- Volatility gauge

#### 3. Strategies (`/strategies`)
- Strategy list with performance metrics
- Backtest results comparison
- Active strategy signals
- Strategy health (is it still performing?)

#### 4. Sentiment (`/sentiment`)
- News feed with sentiment scores
- Reddit/Twitter buzz indicators
- Sentiment vs price divergence alerts
- Historical sentiment chart

#### 5. Trades (`/trades`)
- Trade log (all paper trades)
- Open positions
- P&L breakdown by strategy
- Risk metrics (exposure, VaR)

#### 6. Settings (`/settings`)
- API keys configuration
- Symbol watchlist
- Strategy enable/disable
- Alert thresholds

### Features
- Auto-refresh every 60 seconds (configurable)
- Dark mode (default)
- Mobile-responsive
- WebSocket for real-time updates (stretch goal)
- Export data as CSV

### API Endpoints
- `GET /api/overview` — dashboard summary
- `GET /api/markets/{symbol}` — market data
- `GET /api/strategies` — strategy list + metrics
- `GET /api/signals` — active signals
- `GET /api/trades` — trade history
- `GET /api/sentiment/{symbol}` — sentiment data

## Done Criteria
- [ ] `pytest tests/test_dashboard.py` passes
- [ ] `mypy src/dashboard/` passes
- [ ] FastAPI server starts on localhost:8000
- [ ] Overview page loads with market data
- [ ] Charts render with real data
- [ ] Dark mode works
- [ ] Auto-refresh updates data
- [ ] CLI `python -m src.dashboard` starts server

## Files Expected to Change
- src/dashboard/__init__.py
- src/dashboard/app.py (FastAPI app)
- src/dashboard/routes.py
- src/dashboard/api.py
- src/dashboard/templates/ (Jinja2 templates)
- src/dashboard/static/ (CSS, JS)
- src/dashboard/charts.py (chart generation)
- tests/test_dashboard.py
