# Loop State: Trading Intelligence System

**Goal:** Build a comprehensive trading intelligence platform that accumulates strategies, analyzes markets, makes decisions, and executes trades (paper first, live with approval)
**Status:** IN_PROGRESS
**Created:** 2026-06-21
**Iteration:** 0/15
**Current Milestone:** M1
**Last Good Commit:** 98a8380

## Configuration
- max_iterations: 15
- quality_gates:
  - command: "pytest tests/ -v"
    name: tests
    required: true
  - command: "mypy src/"
    name: typecheck
    required: true
- optional_gates:
  - command: "flake8 src/"
    name: lint
    required: false
- auto_commit: true
- commit_prefix: "iter"
- timeout_per_iteration: 600
- background: false
- background_schedule: "every 10m"

## Budget
- tokens_used: 0
- tokens_budget: 2000000
- cost_estimate: $0.00
- cost_budget: $25.00
- budget_status: OK

## Dependency Graph
```
M1 (no deps) ──→ M2 (deps: M1) ──→ M5 (deps: M1,M2,M4)
    │                │                    ↑
    └──→ M3 (deps: M1) ──→ M4 (deps: M1,M3) ──→ M6 (deps: M3,M4)
                                                    │
                                                    ↓
                                                  M7 (deps: M5,M6) ──→ M8 (deps: M7)
                                                        │
                                                        └──→ M9 (deps: M7,M8)
```
**Parallel opportunities:**
- M1 → then M2 ∥ M3 can run in parallel
- M3 → then M4 can run after M3 completes
- M2 + M4 → M5 needs both
- M3 + M4 → M6 needs both
- M5 + M6 → M7 needs both
- M7 → then M8 ∥ M9 can run in parallel

## Milestones

### M1: Data Foundation [PENDING]
- Description: Market data collection layer (OHLCV, volume, multiple sources)
- Depends on: None
- Done criteria: Fetch and store 1 year of daily data for AAPL, SQLite persistence, rate limiting
- Expected files: src/data/, tests/test_data_collector.py
- Requires approval: false
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M2: News/Sentiment Collector [PENDING]
- Description: Financial news and sentiment scoring from multiple sources
- Depends on: M1
- Done criteria: Fetch and score sentiment for AAPL from 3+ sources, FinBERT working
- Expected files: src/data/sentiment/, tests/test_sentiment.py
- Requires approval: false
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M3: Strategy Library [PENDING]
- Description: 15 proven trading strategies with coded rules and backtesting interface
- Depends on: M1
- Done criteria: 15 strategies loaded, each produces Signal, clean BaseStrategy interface
- Expected files: src/strategy/, configs/strategies/*.yaml
- Requires approval: true (strategy selection affects everything)
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M4: Backtesting Engine [PENDING]
- Description: Run strategies against historical data, calculate metrics, rank performance
- Depends on: M1, M3
- Done criteria: Backtest MA Crossover on AAPL, full metrics, equity curve PNG
- Expected files: src/strategy/backtester.py, tests/test_backtester.py
- Requires approval: false
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M5: Analysis Dashboard [PENDING]
- Description: Web dashboard showing market state, signals, strategy performance
- Depends on: M1, M2, M4
- Done criteria: FastAPI server on :8000, overview page with real data, charts, dark mode
- Expected files: src/dashboard/, tests/test_dashboard.py
- Requires approval: false
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M6: Decision Engine [PENDING]
- Description: Signal aggregation, risk management, trade recommendations
- Depends on: M3, M4
- Done criteria: Generate BUY recommendation with 3+ strategies agreeing, risk management working
- Expected files: src/decision/, tests/test_decision.py
- Requires approval: true (risk parameters need human approval)
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M7: Paper Trading [PENDING]
- Description: Simulated execution, position tracking, P&L, benchmark comparison
- Depends on: M5, M6
- Done criteria: Execute paper trade, track P&L, stop loss/take profit working
- Expected files: src/execution/paper.py, tests/test_paper_trading.py
- Requires approval: true (before any real money implications)
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M8: Broker Integration [PENDING]
- Description: Alpaca API connection, order execution, emergency controls
- Depends on: M7
- Done criteria: Connect to Alpaca paper API, submit/cancel orders, emergency stop
- Expected files: src/execution/broker.py, tests/test_broker.py
- Requires approval: true (live trading requires explicit approval)
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

### M9: Learning Loop [PENDING]
- Description: Track performance, auto-adjust weights, regime detection, insights
- Depends on: M7, M8
- Done criteria: Track outcomes, adjust weights (bounded), regime detection working
- Expected files: src/learning/, tests/test_learning.py
- Requires approval: false
- Tokens used: 0
- Cost estimate: $0.00
- Attempts: 0

## Learnings (append-only)
<!-- Record what went wrong and what was discovered each iteration -->

## Quality Gate History
<!-- Gate results per iteration -->

## Files Changed (running log)
<!-- Which files were modified per iteration -->

## Rollback Log
<!-- Record rollbacks and their reasons -->
