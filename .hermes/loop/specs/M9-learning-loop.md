# Spec: M9 — Learning Loop

## Objective
Track strategy performance over time, auto-adjust weights, and learn from wins/losses to improve future decisions.

## Requirements

### Performance Tracking
```python
@dataclass
class StrategyPerformance:
    strategy_id: str
    period: str  # "1d" | "1w" | "1m" | "3m" | "1y"
    total_signals: int
    signals_taken: int
    win_rate: float
    avg_return: float
    sharpe_ratio: float
    max_drawdown: float
    last_updated: datetime
```

### Weight Adjustment Logic
- **Base weight**: Equal weight across all strategies
- **Performance adjustment**: Weight by recent Sharpe ratio
- **Decay**: Older performance matters less (exponential decay)
- **Minimum weight**: 0.05 (no strategy drops below 5%)
- **Maximum weight**: 0.30 (no strategy dominates above 30%)

### Learning Features
- `track_outcome(trade, result)` — record trade result
- `recalculate_weights()` — adjust strategy weights
- `get_weights()` — current strategy weights
- `get_insights()` — what's working, what's not
- `detect_regime()` — bull/bear/sideways market detection
- `adapt_to_regime(regime)` — adjust strategy mix for market regime

### Regime Detection
- **Bull**: >20 day MA trending up, positive sentiment
- **Bear**: <20 day MA trending down, negative sentiment
- **Sideways**: Range-bound, low volatility
- **High Volatility**: VIX > 25, large daily swings

### Insights Generation
- Which strategies are performing best/worst?
- Which market conditions favor which strategies?
- Are there patterns in losing trades?
- Is the system improving or degrading over time?

### Reporting
- Weekly learning report (what changed, why)
- Monthly strategy rebalance summary
- Quarterly performance review
- Annual strategy audit (retire underperformers)

## Done Criteria
- [ ] `pytest tests/test_learning.py` passes
- [ ] `mypy src/learning/` passes
- [ ] Can track trade outcomes and update weights
- [ ] Weight adjustment is bounded (min 0.05, max 0.30)
- [ ] Regime detection identifies market state
- [ ] Insights are human-readable
- [ ] CLI `python -m src.learning.status`

## Files Expected to Change
- src/learning/__init__.py
- src/learning/tracker.py
- src/learning/weights.py
- src/learning/regime.py
- src/learning/insights.py
- src/learning/reporting.py
- tests/test_learning.py
