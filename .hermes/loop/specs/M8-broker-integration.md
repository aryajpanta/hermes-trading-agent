# Spec: M8 — Broker Integration

## Objective
Connect to Alpaca API for live trading execution with human approval gates.

## Requirements

### Broker: Alpaca Markets
- **API**: REST + WebSocket
- **Paper trading**: Free, instant setup
- **Live trading**: Requires account approval
- **Commission**: $0 for stocks, $0 for crypto

### Safety Gates
```python
@dataclass
class ExecutionConfig:
    mode: str = "PAPER"  # "PAPER" | "LIVE" (requires approval)
    require_approval: bool = True  # human must approve each trade
    max_daily_trades: int = 10
    max_daily_loss_pct: float = 0.02  # auto-pause at -2%
    emergency_stop: bool = False  # kill switch
```

### Features
- `connect(api_key, secret_key)` — connect to Alpaca
- `submit_order(recommendation)` — place order (paper or live)
- `cancel_order(order_id)` — cancel pending order
- `get_positions()` — current positions from broker
- `get_account()` — account balance, buying power
- `get_orders()` — order history
- `sync_portfolio()` — sync local state with broker

### Order Types
- Market orders (immediate execution)
- Limit orders (specified price)
- Stop orders (trigger at price)
- Stop-limit orders

### Approval Flow
```
Decision Engine → Recommendation → Human Approval → Broker Execution
                                      ↓
                                   Rejected → Log + Skip
```

In paper mode: auto-approve (no human gate)
In live mode: require explicit approval via CLI or dashboard

### Emergency Controls
- `emergency_stop()` — cancel all open orders, close all positions
- `pause_trading()` — stop new trades, keep existing
- `resume_trading()` — resume normal operation
- Circuit breaker: auto-pause on 3 consecutive losses

## Done Criteria
- [ ] `pytest tests/test_broker.py` passes
- [ ] `mypy src/execution/broker.py` passes
- [ ] Can connect to Alpaca paper trading API
- [ ] Can submit and cancel orders
- [ ] Portfolio syncs with broker state
- [ ] Human approval required for live trades
- [ ] Emergency stop works
- [ ] CLI `python -m src.execution.broker --account-status`

## Files Expected to Change
- src/execution/broker.py
- src/execution/orders.py
- src/execution/sync.py
- src/execution/emergency.py
- tests/test_broker.py
- configs/broker_config.yaml
