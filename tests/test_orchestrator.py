"""Tests for LearningOrchestrator — the integration end-to-end."""
import tempfile
import os
import numpy as np
import pandas as pd

from src.learning.orchestrator import LearningOrchestrator
from src.learning.features.schema import FEATURE_COLUMNS, LABEL_COLUMN


def _write_fake_labels(dirpath: str, n: int = 30) -> None:
    """Write a fake labels.jsonl with n rows of plausible training data."""
    rng = np.random.default_rng(123)
    rows = []
    for i in range(n):
        row = {
            "ts": f"2026-06-{(i % 30) + 1:02d}T00:00:00+00:00",
            "symbol": ["AAPL", "QQQ", "SPY", "BTC-USD"][i % 4],
            "strategy_id": ["rsi", "macd", "bb", "ma_cross"][i % 4],
            "entry_price": 100.0 + i,
            "entry_qty": 10,
            "entry_ts": f"2026-06-{(i % 30) + 1:02d}T00:00:00+00:00",
            "exit_price": 100.0 + i + rng.normal(0, 2),
            "exit_ts": f"2026-06-{(i % 30) + 1:02d}T01:00:00+00:00",
            "hold_hours": 1.0,
            "realized_pnl_pct": rng.normal(0.01, 0.02),
        }
        # Fill feature columns with random data
        for c in FEATURE_COLUMNS:
            row[c] = float(rng.normal(0, 1))
        rows.append(row)
    with open(os.path.join(dirpath, "labels.jsonl"), "w") as f:
        import json
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def test_orchestrator_initializes():
    with tempfile.TemporaryDirectory() as d:
        orch = LearningOrchestrator(retrain_every_n=5, data_dir=d)
        s = orch.status()
        assert s["model_loaded"] is False
        assert s["current_weights"] == {}


def test_orchestrator_retrains_when_min_trades_reached():
    with tempfile.TemporaryDirectory() as d:
        _write_fake_labels(d, n=30)
        orch = LearningOrchestrator(
            retrain_every_n=5, data_dir=d, min_trades_for_retrain=20
        )
        # Force the closed count above the threshold to trigger retrain
        orch._closed_count = 25
        orch._retrain_and_publish()
        s = orch.status()
        assert s["model_loaded"] is True, "model should be trained after retrain"
        # If gate accepts, weights should be set
        # (depends on Sharpe; we don't assert specific values, just that status is valid)
        assert "feature_importance" in s


def test_orchestrator_skips_retrain_with_too_few_trades():
    with tempfile.TemporaryDirectory() as d:
        _write_fake_labels(d, n=5)
        orch = LearningOrchestrator(
            retrain_every_n=3, data_dir=d, min_trades_for_retrain=20
        )
        orch._closed_count = 5
        orch._retrain_and_publish()
        s = orch.status()
        # Model should not have trained (insufficient data)
        assert s["model_loaded"] is False


def test_orchestrator_handles_trade_entry_and_close():
    """End-to-end: entry then close should record, label, and possibly trigger retrain."""
    with tempfile.TemporaryDirectory() as d:
        # Pre-populate with enough data so retrain can fire
        _write_fake_labels(d, n=22)
        orch = LearningOrchestrator(
            retrain_every_n=3, data_dir=d, min_trades_for_retrain=20
        )
        # One entry + close
        orch.on_trade_entry("AAPL", "rsi", qty=10, entry_price=200.0)
        orch.on_trade_close({"AAPL": 205.0})
        # closed_count should be 1 (last_retrain=0 + 1)
        assert orch._closed_count == 1
        # Force a retrain now to verify
        orch._closed_count = 25
        orch._retrain_and_publish()
        assert orch.status()["model_loaded"] is True


def test_orchestrator_status_shape():
    with tempfile.TemporaryDirectory() as d:
        orch = LearningOrchestrator(data_dir=d)
        s = orch.status()
        expected_keys = {
            "closed_trade_count", "last_retrain_ts", "current_weights",
            "current_sharpe", "feature_importance", "model_loaded",
            "min_trades_for_retrain", "retrain_every_n",
        }
        assert expected_keys.issubset(s.keys())
