"""Automation tests.

Run: pytest tests/test_automation.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.automation.scheduler import (
    AutomationScheduler,
    get_cycles,
    run_tick,
)


class TestRunTick:
    def test_dry_run_returns_cycle(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cycle = run_tick(watchlist=[], dry_run=True)
        assert cycle["type"] == "tick"
        assert "timestamp" in cycle
        assert "duration_s" in cycle
        assert "prices" in cycle
        assert "open_positions" in cycle

    def test_persists_cycle_log(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        run_tick(watchlist=[], dry_run=False)
        log = tmp_path / "data" / "cycles.json"
        assert log.exists()
        entries = json.loads(log.read_text())
        assert len(entries) == 1
        assert entries[0]["type"] == "tick"

    def test_get_cycles(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for _ in range(3):
            run_tick(watchlist=[], dry_run=False)
        cycles = get_cycles(limit=10)
        assert len(cycles) == 3


class TestSchedulerLifecycle:
    def test_disabled_via_env(self, monkeypatch):
        monkeypatch.setenv("ENABLE_AUTOMATION", "false")
        s = AutomationScheduler()
        assert s.enabled is False

    def test_enabled_default(self, monkeypatch):
        monkeypatch.delenv("ENABLE_AUTOMATION", raising=False)
        s = AutomationScheduler()
        assert s.enabled is True

    def test_custom_intervals(self, monkeypatch):
        monkeypatch.setenv("AUTOMATION_INTERVAL_MS", "5000")
        monkeypatch.setenv("REVIEW_INTERVAL_MS", "60000")
        s = AutomationScheduler()
        assert s.monitor_interval_s == 5.0
        assert s.review_interval_s == 60.0

    def test_status(self):
        s = AutomationScheduler(monitor_interval_s=30, review_interval_s=3600)
        st = s.status
        assert "monitor" in st
        assert "review" in st
        assert st["monitor_interval_s"] == 30.0
        assert st["review_interval_s"] == 3600.0
