"""Config tests.

Run: pytest tests/test_config.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def fresh_settings(monkeypatch):
    """Reset the settings singleton for each test."""
    from src import config

    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_KEY_ID", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_MODEL", raising=False)
    monkeypatch.delenv("OPENCODE_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("ENABLE_AUTOMATION", raising=False)
    monkeypatch.delenv("AUTOMATION_INTERVAL_MS", raising=False)
    return config.settings


class TestAlpaca:
    def test_unconfigured(self, fresh_settings):
        assert fresh_settings.alpaca_configured is False

    def test_hta_key_names(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY_ID", "test_id")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "test_secret")
        s = fresh_settings
        assert s.alpaca_key == "test_id"
        assert s.alpaca_secret == "test_secret"
        assert s.alpaca_configured is True

    def test_ti_key_names(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY", "test_id")
        monkeypatch.setenv("ALPACA_SECRET", "test_secret")
        s = fresh_settings
        assert s.alpaca_key == "test_id"
        assert s.alpaca_secret == "test_secret"

    def test_paper_default(self, fresh_settings):
        assert fresh_settings.alpaca_paper is True

    def test_live_mode(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("ALPACA_PAPER", "false")
        assert fresh_settings.alpaca_paper is False


class TestOpenCode:
    def test_unconfigured(self, fresh_settings):
        assert fresh_settings.opencode_configured is False

    def test_configured(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("OPENCODE_API_KEY", "abc123")
        assert fresh_settings.opencode_configured is True

    def test_default_model(self, fresh_settings):
        assert fresh_settings.opencode_model == "mimo-v2.5"
        assert fresh_settings.opencode_reasoning_effort == "high"

    def test_model_override(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("OPENCODE_MODEL", "claude-haiku-4-5")
        assert fresh_settings.opencode_model == "claude-haiku-4-5"


class TestWebhook:
    def test_unconfigured(self, fresh_settings):
        assert fresh_settings.webhook_configured is False

    def test_configured(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", "shh")
        assert fresh_settings.webhook_configured is True


class TestAutomation:
    def test_default_enabled(self, fresh_settings):
        assert fresh_settings.automation_enabled is True

    def test_disabled(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("ENABLE_AUTOMATION", "false")
        assert fresh_settings.automation_enabled is False

    def test_intervals(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("AUTOMATION_INTERVAL_MS", "5000")
        monkeypatch.setenv("REVIEW_INTERVAL_MS", "120000")
        assert fresh_settings.monitor_interval_ms == 5000
        assert fresh_settings.review_interval_ms == 120000


class TestValidation:
    def test_warnings_when_unconfigured(self, fresh_settings):
        warnings = fresh_settings.validate()
        assert len(warnings) == 3  # alpaca, opencode, webhook

    def test_no_warnings_when_configured(self, fresh_settings, monkeypatch):
        monkeypatch.setenv("ALPACA_API_KEY_ID", "id")
        monkeypatch.setenv("ALPACA_SECRET_KEY", "sec")
        monkeypatch.setenv("OPENCODE_API_KEY", "oc")
        monkeypatch.setenv("WEBHOOK_SECRET", "shh")
        warnings = fresh_settings.validate()
        assert warnings == []


class TestSummary:
    def test_summary_shape(self, fresh_settings):
        s = fresh_settings.summary()
        assert "server" in s
        assert "alpaca" in s
        assert "opencode" in s
        assert "webhook" in s
        assert "automation" in s
