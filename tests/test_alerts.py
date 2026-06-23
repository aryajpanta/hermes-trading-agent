"""Alerts engine tests.

Run: pytest tests/test_alerts.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.alerts.store import AlertStore
from src.alerts.monitor import _check_condition


class TestAlertStore:
    def test_add_and_list(self, tmp_path, monkeypatch):
        store = AlertStore(path=tmp_path / "alerts.json")
        a = store.add(
            symbol="BTC",
            asset_class="crypto",
            condition="gte",
            value=75000,
            action="buy",
        )
        assert a["id"].startswith("alert_")
        assert a["symbol"] == "BTC"
        assert a["triggered"] is False
        assert len(store.list()) == 1

    def test_remove(self, tmp_path):
        store = AlertStore(path=tmp_path / "alerts.json")
        a = store.add("BTC", "crypto", "gte", 75000, "buy")
        assert store.remove(a["id"]) is True
        assert store.remove(a["id"]) is False  # already gone
        assert store.list() == []

    def test_reset_all(self, tmp_path):
        store = AlertStore(path=tmp_path / "alerts.json")
        a = store.add("BTC", "crypto", "gte", 75000, "buy")
        store.mark_triggered(a["id"])
        assert store.get(a["id"])["triggered"] is True
        count = store.reset_all()
        assert count == 1
        assert store.get(a["id"])["triggered"] is False

    def test_persistence(self, tmp_path):
        path = tmp_path / "alerts.json"
        s1 = AlertStore(path=path)
        a = s1.add("ETH", "crypto", "lte", 1500, "sell")
        # Reload from disk
        s2 = AlertStore(path=path)
        loaded = s2.get(a["id"])
        assert loaded is not None
        assert loaded["symbol"] == "ETH"
        assert loaded["value"] == 1500


class TestConditions:
    def test_gte(self):
        assert _check_condition(100, "gte", 50, 40) is True
        assert _check_condition(50, "gte", 100, 200) is False

    def test_lte(self):
        assert _check_condition(50, "lte", 100, 200) is True
        assert _check_condition(100, "lte", 50, 40) is False

    def test_cross_above(self):
        # previous < threshold <= current
        assert _check_condition(105, "cross_above", 100, 95) is True
        # No previous: should not cross
        assert _check_condition(105, "cross_above", 100, None) is False
        # Already above previous tick: no cross
        assert _check_condition(110, "cross_above", 100, 105) is False

    def test_cross_below(self):
        assert _check_condition(95, "cross_below", 100, 105) is True
        assert _check_condition(95, "cross_below", 100, None) is False
        assert _check_condition(85, "cross_below", 100, 90) is False
