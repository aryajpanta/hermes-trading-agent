# Spec: M3 — Strategy Library

## Objective
Build a structured library of proven trading strategies, each with coded entry/exit rules, risk parameters, and attribution to their source.

## Requirements

### Strategy Data Model
```python
@dataclass
class Strategy:
    id: str
    name: str
    source: str  # "turtle_traders" | "mark_minervini" | "peter_lynch" | etc.
    description: str
    category: str  # "trend" | "mean_reversion" | "momentum" | "breakout" | "value"
    timeframes: list[str]  # ["1d", "1h", "5m"]
    assets: list[str]  # ["stocks", "crypto", "forex"]
    entry_rules: list[str]  # human-readable conditions
    exit_rules: list[str]
    stop_loss_pct: float
    take_profit_pct: float
    position_size_pct: float
    max_holding_period: int  # days
    min_confidence: float  # 0.0-1.0
```

### Initial Strategy Library (10-15 strategies)

| # | Strategy | Source | Category |
|---|----------|--------|----------|
| 1 | Moving Average Crossover (50/200) | Trend following | Trend |
| 2 | RSI Mean Reversion (30/70) | Welles Wilder | Mean Reversion |
| 3 | MACD Signal Line Cross | Gerald Appel | Momentum |
| 4 | Bollinger Band Breakout | John Bollinger | Breakout |
| 5 | VWAP Reversion | Institutional | Mean Reversion |
| 6 | Turtle Trading System | Richard Dennis | Trend |
| 7 | Minervini SEPA | Mark Minervini | Trend |
| 8 | O'Neil CANSLIM | William O'Neil | Growth |
| 9 | Dividend Growth | Peter Lynch | Value |
| 10 | Volume Profile | Market profile theory | Breakout |
| 11 | ATR Trailing Stop | Wilder | Trend |
| 12 | Ichimoku Cloud | Goichi Hosoda | Trend |
| 13 | Stochastic Oscillator | Lane | Momentum |
| 14 | Fibonacci Retracement | Leonardo Fibonacci | Breakout |
| 15 | Order Flow Imbalance | Prop trading | Momentum |

### Features
- `load_strategies()` — load all from YAML config
- `get_strategy(id)` — get single strategy
- `list_strategies(category, asset_type)` — filtered list
- `evaluate(strategy, market_data)` — generate signal (-1 to +1)
- `add_strategy(strategy_config)` — add custom strategy
- `export_strategies(format)` — YAML/JSON export
- Strategy configs stored in `configs/strategies/` as YAML files
- Each strategy is a Python class implementing a common interface

### Strategy Interface
```python
class BaseStrategy(ABC):
    @abstractmethod
    def evaluate(self, data: pd.DataFrame) -> Signal:
        """Evaluate strategy on data, return signal."""
        pass
    
    @abstractmethod
    def required_indicators(self) -> list[str]:
        """Return list of technical indicators needed."""
        pass
    
    @abstractmethod
    def minimum_data_points(self) -> int:
        """Minimum bars needed for evaluation."""
        pass
```

## Done Criteria
- [ ] `pytest tests/test_strategies.py` passes
- [ ] `mypy src/strategy/` passes
- [ ] 15 strategies loaded from config
- [ ] Each strategy produces a Signal on test data
- [ ] Strategy interface is clean and extensible
- [ ] CLI `python -m src.strategy.list` shows all strategies
- [ ] Adding a new strategy requires only a YAML config + Python class

## Files Expected to Change
- src/strategy/__init__.py
- src/strategy/base.py (BaseStrategy ABC)
- src/strategy/library.py (strategy registry)
- src/strategy/signals.py (Signal dataclass)
- src/strategy/strategies/ (one file per strategy)
- configs/strategies/*.yaml (15 strategy configs)
- tests/test_strategies.py
