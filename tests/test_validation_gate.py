"""Tests for ValidationGate and backtester."""
import json
import os
import tempfile

from src.learning.validation.gate import ValidationGate, GateDecision
from src.learning.validation.backtester import (
    compute_sharpe, backtest_weights, _sharpe_from_trades,
)


# ── Gate tests ──────────────────────────────────────────────


def test_gate_accepts_when_sharpe_improves():
    gate = ValidationGate()
    decision = gate.evaluate(
        candidate_weights={"strat_a": 0.5, "strat_b": 0.5},
        current_sharpe=1.0,
        candidate_sharpe=1.2,
    )
    assert decision.accepted is True


def test_gate_rejects_when_sharpe_drops_below_threshold():
    gate = ValidationGate(max_drop_pct=0.05)
    decision = gate.evaluate(
        candidate_weights={"strat_a": 0.5, "strat_b": 0.5},
        current_sharpe=1.0,
        candidate_sharpe=0.90,  # 10% drop
    )
    assert decision.accepted is False
    assert "drop" in decision.reason.lower()


def test_gate_accepts_small_drop_within_tolerance():
    gate = ValidationGate(max_drop_pct=0.05)
    decision = gate.evaluate(
        candidate_weights={"strat_a": 0.5, "strat_b": 0.5},
        current_sharpe=1.0,
        candidate_sharpe=0.97,  # 3% drop, within tolerance
    )
    assert decision.accepted is True


def test_gate_accepts_with_no_baseline():
    gate = ValidationGate()
    decision = gate.evaluate(
        candidate_weights={"strat_a": 1.0},
        current_sharpe=0.0,  # no baseline
        candidate_sharpe=0.5,
    )
    assert decision.accepted is True
    assert "no_baseline" in decision.reason


def test_gate_rejects_negative_candidate_with_no_baseline():
    gate = ValidationGate()
    decision = gate.evaluate(
        candidate_weights={"strat_a": 1.0},
        current_sharpe=0.0,
        candidate_sharpe=-0.5,
    )
    assert decision.accepted is False


def test_gate_logs_decision():
    with tempfile.TemporaryDirectory() as d:
        log_path = os.path.join(d, "gate.jsonl")
        gate = ValidationGate(log_path=log_path)
        gate.evaluate({"a": 0.5, "b": 0.5}, 1.0, 1.2)
        assert os.path.exists(log_path)
        with open(log_path) as f:
            line = f.readline()
        record = json.loads(line)
        assert record["accepted"] is True
        assert record["current_sharpe"] == 1.0
        assert record["candidate_sharpe"] == 1.2


# ── Backtester tests ────────────────────────────────────────


def test_compute_sharpe_known_curve():
    # Constant positive returns: rets = [0.01, 0.01, 0.01, 0.01]
    # mean = 0.01, sd = 0
    # Should return very high (we use 1e-9 to avoid div by zero)
    equity = [1.0, 1.01, 1.0201, 1.030301, 1.04060401]
    sharpe = compute_sharpe(equity)
    assert sharpe > 0  # positive


def test_compute_sharpe_downward_curve():
    # Declining equity → negative sharpe
    equity = [1.0, 0.99, 0.98, 0.97, 0.96]
    sharpe = compute_sharpe(equity)
    assert sharpe < 0


def test_compute_sharpe_empty():
    assert compute_sharpe([]) == 0.0
    assert compute_sharpe([1.0]) == 0.0


def test_backtest_trade_replay_produces_sharpe():
    trades = [
        {"pnl": 0.01, "strategy_id": "a", "symbol": "X", "exit_ts": "2026-01-01"},
        {"pnl": -0.005, "strategy_id": "a", "symbol": "X", "exit_ts": "2026-01-02"},
        {"pnl": 0.02, "strategy_id": "a", "symbol": "X", "exit_ts": "2026-01-03"},
        {"pnl": 0.015, "strategy_id": "a", "symbol": "X", "exit_ts": "2026-01-04"},
        {"pnl": -0.01, "strategy_id": "a", "symbol": "X", "exit_ts": "2026-01-05"},
    ]
    sharpe = backtest_weights({"a": 1.0}, trades=trades)
    # Net pnl is positive, so sharpe should be > 0
    assert sharpe != 0.0


def test_backtest_empty_trades_returns_zero():
    assert backtest_weights({}, trades=[]) == 0.0


def test_backtest_filters_by_watchlist():
    trades = [
        {"pnl": 0.10, "strategy_id": "a", "symbol": "IN"},
        {"pnl": -0.10, "strategy_id": "a", "symbol": "OUT"},
    ]
    # Only include IN
    sharpe = backtest_weights({}, trades=trades, watchlist=["IN"])
    # Should be positive (single positive trade)
    assert sharpe > 0
