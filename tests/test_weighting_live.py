"""Tests for LiveWeightAdapter."""
from src.learning.weighting.live import LiveWeightAdapter, MIN_WEIGHT


def test_weights_bounded():
    """All weights must be >= MIN_WEIGHT."""
    a = LiveWeightAdapter()
    raw = {"strat_a": 0.10, "strat_b": -0.05, "strat_c": 0.001}
    w = a.from_expected_pnl(raw)
    assert all(v >= MIN_WEIGHT - 1e-9 for v in w.values()), (
        f"weights below MIN_WEIGHT: {w}"
    )
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_better_strategy_gets_higher_weight():
    a = LiveWeightAdapter()
    w = a.from_expected_pnl({"good": 0.10, "bad": -0.10, "neutral": 0.0})
    assert w["good"] > w["bad"], f"good should beat bad: {w}"
    assert w["good"] > w["neutral"], f"good should beat neutral: {w}"


def test_handles_empty_input():
    a = LiveWeightAdapter()
    assert a.from_expected_pnl({}) == {}


def test_handles_all_negative():
    """All negative expected PnL — should still produce valid weights >= MIN_WEIGHT."""
    a = LiveWeightAdapter()
    w = a.from_expected_pnl({"a": -0.05, "b": -0.02, "c": -0.01})
    assert all(v >= MIN_WEIGHT - 1e-9 for v in w.values()), f"weights below min: {w}"
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_sums_to_one():
    a = LiveWeightAdapter()
    raw = {"a": 0.01, "b": 0.02, "c": 0.03, "d": -0.01, "e": 0.005}
    w = a.from_expected_pnl(raw)
    assert abs(sum(w.values()) - 1.0) < 1e-6
    assert len(w) == 5


def test_more_strategies_better_signal_amplification():
    """With 15 strategies, a strong positive signal should get more weight than
    a weak one (within bounds)."""
    a = LiveWeightAdapter()
    expected = {f"strat_{i}": 0.0 for i in range(14)}
    expected["hot"] = 0.10
    w = a.from_expected_pnl(expected)
    # Hot should be higher than average
    avg = 1.0 / 15
    assert w["hot"] > avg * 1.5, f"hot should be > 1.5x avg, got {w['hot']} vs avg {avg}"


def test_extreme_signal_does_not_exceed_caps():
    """Even with a 50% expected PnL, no weight should be wildly above the rest.
    The soft cap + projection + renormalize keeps things from going insane.
    Specifically: with 4 strategies and a hot signal of 0.50, the 'hot' weight
    can be up to ~3-4x the equal-share (0.25). This test asserts boundedness."""
    a = LiveWeightAdapter()
    expected = {"hot": 0.50, "cold1": 0.0, "cold2": 0.0, "cold3": 0.0}
    w = a.from_expected_pnl(expected)
    # The hot strategy should be the largest
    assert max(w.values()) == w["hot"]
    # Cold strategies should be near equal weight (close to 1/N)
    cold_avg = (w["cold1"] + w["cold2"] + w["cold3"]) / 3
    assert 0.05 <= cold_avg <= 0.20, f"cold strategies not balanced: {w}"
    # Hot should beat cold but not absurdly
    assert w["hot"] < 0.80, f"hot weight too extreme: {w}"
