# Spec: M6 — Decision Engine

## Objective
Combine signals from multiple strategies, apply risk management rules, and generate trade recommendations with confidence scores.

## Requirements

### Signal Aggregation
```python
@dataclass
class TradeRecommendation:
    symbol: str
    direction: str  # "BUY" | "SELL" | "HOLD"
    confidence: float  # 0.0-1.0
    strategies_agreeing: list[str]  # which strategies fired
    strategies_disagreeing: list[str]
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size_pct: float  # % of portfolio
    risk_reward_ratio: float
    reasoning: str  # human-readable explanation
    timestamp: datetime
```

### Risk Management Rules
```python
@dataclass
class RiskConfig:
    max_position_pct: float = 0.05  # 5% per trade
    max_portfolio_risk: float = 0.02  # 2% daily loss limit
    max_correlated_positions: int = 3  # max positions in correlated assets
    min_confidence: float = 0.6  # minimum signal confidence
    min_strategies_agreeing: int = 2  # minimum strategies to agree
    max_holding_period_days: int = 30
    stop_loss_atr_multiple: float = 2.0  # 2x ATR for stop loss
```

### Decision Logic
1. Collect signals from all active strategies for a symbol
2. Calculate aggregate signal (weighted by strategy historical performance)
3. Apply confidence threshold (min 0.6)
4. Check agreement threshold (min 2 strategies agree)
5. Calculate position size (Kelly criterion or fixed fractional)
6. Set stop loss and take profit levels
7. Check portfolio-level risk (daily loss limit, correlation)
8. Generate recommendation with full reasoning

### Position Sizing
- **Primary**: Kelly Criterion (fractional Kelly for safety)
- **Fallback**: Fixed fractional (risk 1% per trade)
- **Conservative**: Never risk more than 5% on single position

### Features
- `analyze(symbol)` — generate trade recommendation
- `analyze_portfolio()` — check all holdings for rebalancing
- `check_risk(portfolio)` — validate against risk rules
- `explain(recommendation)` — human-readable reasoning
- `simulate(recommendation)` — what-if analysis
- Full audit log of every decision and why

### Decision Logging
Every decision is logged with:
- Input data snapshot
- Strategy signals
- Risk check results
- Final recommendation
- Confidence score
- Reasoning text

## Done Criteria
- [ ] `pytest tests/test_decision.py` passes
- [ ] `mypy src/decision/` passes
- [ ] Can generate BUY recommendation for AAPL with 3+ strategies agreeing
- [ ] Risk management blocks over-concentrated positions
- [ ] Stop loss and take profit are calculated correctly
- [ ] Decision reasoning is human-readable
- [ ] CLI `python -m src.decision.analyze --symbol AAPL`

## Files Expected to Change
- src/decision/__init__.py
- src/decision/engine.py (main decision engine)
- src/decision/signals.py (signal aggregation)
- src/decision/risk.py (risk management)
- src/decision/position_sizing.py
- src/decision/logging.py (audit log)
- src/decision/models.py
- tests/test_decision.py
