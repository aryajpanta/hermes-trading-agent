"""Tests for the learning integration shim."""
import os
from unittest.mock import MagicMock

from src.learning import integration
from src.learning.integration import (
    set_orchestrator, get_orchestrator, is_learning_enabled,
    notify_entry, notify_close,
)


def setup_function(function):
    """Reset the orchestrator between tests."""
    integration._orchestrator = None
    integration._LEARNER_DISABLED = False


def test_no_orchestrator_is_noop():
    """Without an orchestrator, all notifies are silent no-ops."""
    set_orchestrator(None)
    assert is_learning_enabled() is False
    # These should not raise
    notify_entry("AAPL", "rsi", 10, 200.0)
    notify_close("AAPL", 205.0, "rsi")


def test_orchestrator_receives_entry():
    """With an orchestrator, notify_entry calls on_trade_entry."""
    mock = MagicMock()
    set_orchestrator(mock)
    assert is_learning_enabled() is True
    notify_entry("AAPL", "rsi", 10, 200.0)
    mock.on_trade_entry.assert_called_once_with("AAPL", "rsi", 10, 200.0)


def test_orchestrator_receives_close():
    mock = MagicMock()
    set_orchestrator(mock)
    notify_close("AAPL", 205.0, "rsi")
    mock.on_trade_close.assert_called_once_with({"AAPL": 205.0})


def test_orchestrator_error_does_not_propagate():
    """If the orchestrator throws, the trade code shouldn't be affected."""
    mock = MagicMock()
    mock.on_trade_entry.side_effect = RuntimeError("kaboom")
    set_orchestrator(mock)
    # Should not raise
    notify_entry("AAPL", "rsi", 10, 200.0)


def test_learner_disabled_env(monkeypatch):
    """LEARNER_DISABLED=1 disables even with an orchestrator attached."""
    monkeypatch.setenv("LEARNER_DISABLED", "1")
    integration._LEARNER_DISABLED = True
    mock = MagicMock()
    set_orchestrator(mock)
    assert is_learning_enabled() is False
    notify_entry("AAPL", "rsi", 10, 200.0)
    mock.on_trade_entry.assert_not_called()
