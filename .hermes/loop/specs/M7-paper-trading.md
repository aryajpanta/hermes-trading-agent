# Spec: M7 — Paper Trading

## Objective
Simulated trade execution that tracks positions, P&L, and compares performance to benchmarks.

## Requirements

### Paper Trading Engine
```python
@dataclass
class Position:
    symbol: str
    direction: str  # "LONG" | "SHORT"
    entry_price: float
    entry_time: datetime
    quantity: float
    stop_loss: float
    take_profit: float
    strategy_id: str
    unrealized_pnl: float
    status: str  # "OPEN" | "CLOSED"

@dataclass
class Portfolio:
    cash: float
    positions: list[Position]
    total_value: float
    daily_pnl: float
    total_pnl: float
    win_rate: float
    sharpe_ratio: float
```

### Features
- `execute_signal(recommendation)` — open/close positions
- `update_positions(market_data)` — update unrealized P&L
- `check_stops(market_data)` — trigger stop loss/take profit
- `get_portfolio()` — current portfolio state
- `get_history()` — all historical trades
- `get_performance()` — performance metrics
- `export_trades(format)` — CSV/JSON export
- Starting capital: $100,000 (configurable)
- Real-time position valuation
- Automatic stop loss/take profit execution

### Benchmark Comparison
- Compare portfolio performance to:
  - Buy & Hold (S&P 500)
  - Buy & Hold (BTC)
  - Risk-free rate (Treasury bills)
- Calculate alpha and beta vs benchmarks

### Reporting
- Daily P&L summary
- Weekly performance report
- Monthly drawdown analysis
- Trade distribution (win/loss size)
- Strategy attribution (which strategies made money)

## Done Criteria
- [ ] `pytest tests/test_paper_trading.py` passes
- [ ] `mypy src/execution/paper.py` passes
- [ ] Can execute a paper trade and track P&L
- [ ] Stop loss and take profit trigger correctly
- [ ] Portfolio valuation updates with market data
- [ ] Performance metrics calculated correctly
- [ ] Benchmark comparison works
- [ ] CLI `python -m src.execution.paper --portfolio-status`

## Files Expected to Change
- src/execution/__init__.py
- src/execution/paper.py
- src/execution/portfolio.py
- src/execution/position.py
- src/execution/benchmark.py
- src/execution/reporting.py
- tests/test_paper_trading.py
