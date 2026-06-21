# Spec: M4 — Backtesting Engine

## Objective
Run strategies against historical data, calculate performance metrics, and rank strategies by risk-adjusted returns.

## Requirements

### Backtesting Engine
```python
@dataclass
class BacktestResult:
    strategy_id: str
    symbol: str
    period: str
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_holding_period: float
    trade_log: list[Trade]
```

### Performance Metrics
- **Returns**: Total, annualized, monthly breakdown
- **Risk**: Sharpe ratio, Sortino ratio, max drawdown, volatility
- **Trades**: Win rate, profit factor, avg win/loss, expectancy
- **Risk-adjusted**: Calmar ratio, recovery factor

### Features
- `backtest(strategy, symbol, start, end)` — run single backtest
- `backtest_all(strategies, symbols, period)` — batch backtest
- `rank_strategies(results, metric)` — rank by Sharpe, return, etc.
- `compare_strategies(ids, symbol)` — head-to-head comparison
- `generate_report(results)` — HTML/Markdown report
- Commission modeling (configurable fee per trade)
- Slippage modeling (configurable)
- Walk-forward analysis (in-sample/out-of-sample)
- Monte Carlo simulation for confidence intervals

### Commission Model
```python
@dataclass
class CommissionConfig:
    per_trade_fee: float = 0.0  # $0 for crypto on most exchanges
    per_share_fee: float = 0.0  # $0 for commission-free brokers
    spread_pct: float = 0.001  # 0.1% spread assumption
```

### Reports
- Per-strategy performance summary
- Equity curves (saved as PNG)
- Drawdown charts
- Monthly return heatmap
- Trade distribution analysis

## Done Criteria
- [ ] `pytest tests/test_backtester.py` passes
- [ ] `mypy src/strategy/backtester.py` passes
- [ ] Can backtest MA Crossover on AAPL for 2024 and get full metrics
- [ ] Sharpe ratio, max drawdown, win rate are calculated correctly
- [ ] Commission modeling affects results realistically
- [ ] Equity curve PNG generated
- [ ] Strategies ranked by Sharpe ratio
- [ ] CLI `python -m src.strategy.backtest --strategy ma_crossover --symbol AAPL --start 2024-01-01`

## Files Expected to Change
- src/strategy/backtester.py
- src/strategy/metrics.py
- src/strategy/reports.py
- src/strategy/equity_curve.py
- tests/test_backtester.py
- tests/data/test_backtest_data.py
