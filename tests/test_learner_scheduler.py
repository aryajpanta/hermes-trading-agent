"""Tests for LearnerScheduler."""
import tempfile
from src.learning.scheduler import LearnerScheduler, SchedulerState


def test_scheduler_triggers_retrain_after_n_trades():
    sched = LearnerScheduler(retrain_every_n=5)
    assert sched.should_retrain(closed_trade_count=0) is False
    assert sched.should_retrain(closed_trade_count=4) is False
    assert sched.should_retrain(closed_trade_count=5) is True
    assert sched.should_retrain(closed_trade_count=10) is True
    assert sched.should_retrain(closed_trade_count=11) is True  # continue triggering


def test_scheduler_does_not_retrain_after_mark():
    """After mark_retrained, the counter resets — should_retrain returns False
    until we've accumulated N more trades."""
    with tempfile.TemporaryDirectory() as d:
        sched = LearnerScheduler(
            retrain_every_n=5, state_path=f"{d}/state.json"
        )
        sched.mark_retrained(
            new_weights={"a": 0.5, "b": 0.5}, sharpe=1.0, closed_trade_count=5,
        )
        # Now closed_trade_count=5, last_retrain_trade_count=5, so no retrain
        assert sched.should_retrain(5) is False
        # At 10 (5 more trades) we should retrain again
        assert sched.should_retrain(10) is True


def test_scheduler_persists_state():
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/state.json"
        s1 = LearnerScheduler(retrain_every_n=3, state_path=path)
        s1.mark_retrained({"a": 0.5, "b": 0.5}, sharpe=0.7, closed_trade_count=3)
        # New instance reads the same state
        s2 = LearnerScheduler(retrain_every_n=3, state_path=path)
        assert s2.state.last_retrain_trade_count == 3
        assert s2.state.published_weights == {"a": 0.5, "b": 0.5}
        assert s2.state.current_sharpe == 0.7


def test_trades_since_retrain():
    with tempfile.TemporaryDirectory() as d:
        sched = LearnerScheduler(
            retrain_every_n=5, state_path=f"{d}/state.json"
        )
        sched.mark_retrained({"a": 1.0}, closed_trade_count=10)
        assert sched.trades_since_retrain(15) == 5
        assert sched.trades_since_retrain(10) == 0


def test_default_state_is_empty():
    with tempfile.TemporaryDirectory() as d:
        sched = LearnerScheduler(state_path=f"{d}/state.json")
        assert sched.state.last_retrain_trade_count == 0
        assert sched.state.published_weights is None
        assert sched.state.current_sharpe == 0.0
