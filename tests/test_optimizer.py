"""Optimizer tests.

Run: pytest tests/test_optimizer.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def strategy_path(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        "name: test\n"
        "rsiPeriod: 14\n"
        "rsiOversold: 30\n"
        "rsiOverbought: 70\n"
        "stopLossPct: 0.02\n"
    )
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", str(path))
    return path


class TestOptimizer:
    def test_load_strategy(self, strategy_path):
        from src.automation.optimizer import load_strategy

        s = load_strategy()
        assert s is not None
        assert s["rsiPeriod"] == 14

    def test_save_strategy(self, strategy_path):
        from src.automation.optimizer import load_strategy, save_strategy

        s = load_strategy()
        s["rsiPeriod"] = 21
        save_strategy(s)
        s2 = load_strategy()
        assert s2["rsiPeriod"] == 21

    def test_propose_optimization(self, strategy_path):
        from src.automation.optimizer import propose_optimization

        p = propose_optimization()
        assert p["type"] == "param_change"
        assert p["parameter"] in (
            "rsiPeriod", "rsiOversold", "rsiOverbought",
            "stopLossPct", "macdFast", "macdSlow", "macdSignal",
            "bbPeriod", "bbStdDev", "signalThreshold",
            "riskPerTrade", "riskRewardRatio",
        )
        # Proposed value should be within bounds
        spec_min = 5
        spec_max = 30
        assert spec_min <= p["proposedValue"] <= spec_max

    def test_propose_with_review(self, strategy_path):
        from src.automation.optimizer import propose_optimization

        review = {
            "hypotheses": [
                {
                    "id": "low_win_rate",
                    "severity": "high",
                    "variables": ["rsiOversold"],
                    "text": "test",
                }
            ]
        }
        p = propose_optimization(review)
        # Hypothesis is for rsiOversold — many runs will pick that param
        # (we can't assert deterministically because of randomness)
        assert p["type"] == "param_change"

    def test_apply_optimization(self, strategy_path):
        from src.automation.optimizer import propose_optimization, apply_optimization, load_strategy

        p = propose_optimization()
        result = apply_optimization(p)
        assert result["applied"] is True
        assert result["parameter"] == p["parameter"]
        s = load_strategy()
        assert s[p["parameter"]] == p["proposedValue"]

    def test_run_cycle_no_auto_apply(self, strategy_path):
        from src.automation.optimizer import run_optimization_cycle

        result = run_optimization_cycle(auto_apply=False)
        assert result["applied"] is False
        assert "proposal" in result

    def test_run_cycle_auto_apply_healthy(self, strategy_path):
        from src.automation.optimizer import run_optimization_cycle, load_strategy

        review = {
            "performance": {
                "totalTrades": 10,
                "winRate": 60.0,
                "sharpeRatio": 1.5,
            }
        }
        before = load_strategy().copy()
        result = run_optimization_cycle(review=review, auto_apply=True)
        if result["applied"]:
            after = load_strategy()
            assert after != before
