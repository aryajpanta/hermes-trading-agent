"""Review tests.

Run: pytest tests/test_review.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.automation.review import (
    _calc_metrics,
    _analyze_by_symbol,
    _generate_hypotheses,
    run_review_cycle,
    get_latest_review,
)


class TestMetrics:
    def test_empty(self):
        m = _calc_metrics([])
        assert m["totalTrades"] == 0
        assert m["winRate"] == 0.0

    def test_winning_trades(self):
        trades = [{"pnl": 100}, {"pnl": 50}, {"pnl": -20}]
        m = _calc_metrics(trades)
        assert m["totalTrades"] == 3
        assert m["wins"] == 2
        assert m["losses"] == 1
        assert abs(m["winRate"] - 66.67) < 0.5
        assert m["totalPnl"] == 130.0

    def test_sharpe_nonzero(self):
        trades = [{"pnl": p} for p in [10, -5, 15, -8, 20]]
        m = _calc_metrics(trades)
        assert m["sharpeRatio"] != 0.0


class TestBySymbol:
    def test_breakdown(self):
        trades = [
            {"symbol": "BTC", "pnl": 100},
            {"symbol": "BTC", "pnl": -50},
            {"symbol": "ETH", "pnl": 200},
        ]
        b = _analyze_by_symbol(trades)
        assert b["BTC"]["trades"] == 2
        assert b["BTC"]["wins"] == 1
        assert b["ETH"]["trades"] == 1
        assert b["ETH"]["wins"] == 1


class TestHypotheses:
    def test_low_sample(self):
        h = _generate_hypotheses({"totalTrades": 2, "winRate": 50.0}, {})
        assert any(x["id"] == "low_sample_size" for x in h)

    def test_low_win_rate(self):
        h = _generate_hypotheses(
            {"totalTrades": 10, "winRate": 20.0, "sharpeRatio": 0.5},
            {},
        )
        assert any(x["id"] == "low_win_rate" for x in h)

    def test_healthy_no_alerts(self):
        h = _generate_hypotheses(
            {"totalTrades": 20, "winRate": 60.0, "sharpeRatio": 1.5},
            {},
        )
        assert not any(x["id"] == "low_win_rate" for x in h)


class TestReviewCycle:
    def test_run_with_no_trades(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r = run_review_cycle()
        assert "timestamp" in r
        assert r["cycle"] == 1
        assert r["performance"]["totalTrades"] == 0
        assert get_latest_review() is not None

    def test_increments_cycle(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        r1 = run_review_cycle()
        r2 = run_review_cycle()
        assert r2["cycle"] == r1["cycle"] + 1
