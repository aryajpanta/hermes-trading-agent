# Trading Intelligence System

A comprehensive trading intelligence platform that accumulates strategies from proven traders, analyzes market data across multiple dimensions, makes informed decisions with risk management, and executes trades (starting with paper trading).

## Architecture

```
Data Layer → Strategy Layer → Analysis Layer → Decision Layer → Execution Layer → Learning Layer
```

## Tech Stack

- **Language:** Python 3.11+
- **Data:** yfinance, ccxt, alpha_vantage, SQLite
- **Backtesting:** vectorbt or backtrader
- **Analysis:** pandas, ta-lib, numpy, transformers (FinBERT)
- **Dashboard:** FastAPI + Jinja2 (lightweight)
- **Execution:** Alpaca API (paper + live)
- **Orchestration:** Hermes iterative-loop

## Quick Start

```bash
cd trading-intelligence
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Milestones

| M | Milestone | Status |
|---|-----------|--------|
| M1 | Data Foundation | ⏳ |
| M2 | News/Sentiment Collector | ⏳ |
| M3 | Strategy Library | ⏳ |
| M4 | Backtesting Engine | ⏳ |
| M5 | Analysis Dashboard | ⏳ |
| M6 | Decision Engine | ⏳ |
| M7 | Paper Trading | ⏳ |
| M8 | Broker Integration | ⏳ |
| M9 | Learning Loop | ⏳ |

## Safety

- All execution starts in paper trading mode
- Human approval required for live trading
- Position size limits: max 5% per trade
- Daily loss limit: auto-pause at -2%
- Every decision logged with reasoning
