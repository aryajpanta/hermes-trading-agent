"""End-to-end validation: synthesize 30 plausible historical trades, feed them
through the orchestrator's full pipeline, and assert that the model trains,
the gate makes a decision, and the weights are sensible.

This is the offline equivalent of running the live ticker for 24h.
"""
import tempfile
import json
import os
import numpy as np
import pandas as pd

from src.learning.orchestrator import LearningOrchestrator
from src.learning.features.schema import FEATURE_COLUMNS, LABEL_COLUMN


def _synthesize_trades(
    n: int = 30, seed: int = 42,
) -> list:
    """Generate n synthetic historical trades with realistic feature vectors.

    The signal: 'rsi_mean_reversion' strategy does well when RSI is extreme
    (oversold/overbought) AND volume is high. 'ma_crossover' does well in
    low-volatility trending markets.
    """
    rng = np.random.default_rng(seed)
    strategies = ["rsi_mean_reversion", "ma_crossover", "bb_squeeze", "macd_trend"]
    symbols = ["AAPL", "QQQ", "SPY", "BTC-USD", "ETH-USD"]
    rows = []
    for i in range(n):
        sid = strategies[i % len(strategies)]
        sym = symbols[i % len(symbols)]
        # Generate feature vector
        features = {c: float(rng.normal(0, 1)) for c in FEATURE_COLUMNS}
        # Strategy-specific signal in the features
        if sid == "rsi_mean_reversion":
            features["rsi_14"] = rng.choice([20.0, 80.0]) + rng.normal(0, 5)
            features["volume_zscore_20d"] = 1.5
        elif sid == "ma_crossover":
            features["realized_vol_1d"] = 0.005
            features["adx_14"] = 30.0
        # Build the label
        if sid == "rsi_mean_reversion":
            pnl = 0.02 + 0.005 * features["volume_zscore_20d"] + rng.normal(0, 0.01)
        elif sid == "ma_crossover":
            pnl = 0.015 + 0.001 * features["adx_14"] + rng.normal(0, 0.008)
        else:
            pnl = rng.normal(0.005, 0.015)
        entry_price = 100.0 + i
        exit_price = entry_price * (1 + pnl)
        row = {
            "ts": f"2026-06-{(i % 30) + 1:02d}T00:00:00+00:00",
            "symbol": sym,
            "strategy_id": sid,
            "entry_price": entry_price,
            "entry_qty": 10.0,
            "entry_ts": f"2026-06-{(i % 30) + 1:02d}T00:00:00+00:00",
            "exit_price": exit_price,
            "exit_ts": f"2026-06-{(i % 30) + 1:02d}T01:00:00+00:00",
            "hold_hours": 1.0,
            LABEL_COLUMN: pnl,
            **features,
        }
        rows.append(row)
    return rows


def test_end_to_end_synthetic_validation():
    """Synthesize 30 trades, feed through orchestrator, verify learning works."""
    with tempfile.TemporaryDirectory() as d:
        # Pre-populate with synthetic trades
        trades = _synthesize_trades(n=30)
        jsonl_path = os.path.join(d, "labels.jsonl")
        with open(jsonl_path, "w") as f:
            for t in trades:
                f.write(json.dumps(t, default=str) + "\n")

        # Create the orchestrator with the synthetic data dir
        orch = LearningOrchestrator(
            retrain_every_n=5, data_dir=d, min_trades_for_retrain=20,
        )

        # Status before retrain
        s_before = orch.status()
        assert s_before["model_loaded"] is False, "model shouldn't be trained yet"

        # Force a retrain (simulating 25 closed trades triggering the cadence)
        orch._closed_count = 25
        orch._retrain_and_publish()

        # Status after retrain
        s_after = orch.status()
        assert s_after["model_loaded"] is True, "model should be trained after retrain"
        assert len(s_after["feature_importance"]) > 0, "should have feature importances"

        # The 'rsi_mean_reversion' strategy should have a positive expected PnL
        # since it had the strongest signal in our synthetic data
        # (We don't assert specific weights — gate may accept or reject —
        # but the model should at least be able to predict.)
        df = orch.labeler.load_all()
        assert len(df) >= 25, f"should have at least 25 labeled rows, got {len(df)}"

        print(f"✓ E2E validation passed:")
        print(f"  - {len(df)} labeled rows loaded")
        print(f"  - {len(s_after['feature_importance'])} features with importance")
        print(f"  - Top 3 features: {list(s_after['feature_importance'].items())[:3]}")
        print(f"  - Current weights: {s_after['current_weights']}")


def test_gate_actually_evaluates():
    """After enough synthetic trades, the gate should evaluate and log a decision."""
    with tempfile.TemporaryDirectory() as d:
        trades = _synthesize_trades(n=30, seed=99)
        with open(os.path.join(d, "labels.jsonl"), "w") as f:
            for t in trades:
                f.write(json.dumps(t, default=str) + "\n")

        orch = LearningOrchestrator(
            retrain_every_n=5, data_dir=d, min_trades_for_retrain=20,
        )
        orch._closed_count = 30
        orch._retrain_and_publish()

        # Read the gate log
        gate_log_path = os.path.join(d, "gate_log.jsonl")
        assert os.path.exists(gate_log_path), "gate log should exist after retrain"
        with open(gate_log_path) as f:
            decisions = [json.loads(l) for l in f]
        assert len(decisions) >= 1, "should have at least one gate decision"
        d0 = decisions[0]
        assert "accepted" in d0
        assert "reason" in d0
        assert "current_sharpe" in d0
        assert "candidate_sharpe" in d0
        print(f"✓ Gate evaluated: accepted={d0['accepted']}, reason={d0['reason']}")


def test_weights_bounded_after_learning():
    """After learning, the published weights should be in valid bounds."""
    with tempfile.TemporaryDirectory() as d:
        trades = _synthesize_trades(n=30, seed=7)
        with open(os.path.join(d, "labels.jsonl"), "w") as f:
            for t in trades:
                f.write(json.dumps(t, default=str) + "\n")

        orch = LearningOrchestrator(
            retrain_every_n=5, data_dir=d, min_trades_for_retrain=20,
        )
        orch._closed_count = 30
        orch._retrain_and_publish()

        weights = orch.get_current_weights()
        if weights:
            # If gate accepted, weights should be present
            s = sum(weights.values())
            assert abs(s - 1.0) < 1e-6, f"weights should sum to 1, got {s}"
            from src.learning.weighting.live import MIN_WEIGHT
            for name, w in weights.items():
                assert w >= MIN_WEIGHT - 1e-9, f"{name} weight below MIN: {w}"
            print(f"✓ Published weights valid: {weights}")


if __name__ == "__main__":
    print("Running E2E validation...")
    test_end_to_end_synthetic_validation()
    print()
    test_gate_actually_evaluates()
    print()
    test_weights_bounded_after_learning()
    print()
    print("=" * 60)
    print("ALL E2E VALIDATION TESTS PASSED")
    print("=" * 60)
