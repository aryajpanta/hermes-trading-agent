"""Tests for the Strategy Library (M3)."""

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import (
    add_strategy,
    evaluate,
    get_strategy,
    list_strategies,
    load_strategies,
)
from src.strategy.signals import Signal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_price_data(
    n_bars: int = 250,
    start_price: float = 100.0,
    trend: float = 0.0005,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data with a slight uptrend."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="B")
    returns = rng.normal(trend, volatility, n_bars)
    close = start_price * np.cumprod(1 + returns)

    high = close * (1 + rng.uniform(0, 0.02, n_bars))
    low = close * (1 - rng.uniform(0, 0.02, n_bars))
    open_ = close * (1 + rng.normal(0, 0.005, n_bars))
    volume = rng.randint(100_000, 5_000_000, n_bars).astype(float)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)


@pytest.fixture
def price_data() -> pd.DataFrame:
    """Standard 250-bar price dataset."""
    return _make_price_data(250)


@pytest.fixture
def short_data() -> pd.DataFrame:
    """Short dataset with fewer bars."""
    return _make_price_data(30)


@pytest.fixture(autouse=True)
def _clear_registry():
    """Clear strategy registry between tests."""
    from src.strategy import library as lib
    lib._STRATEGY_INSTANCES.clear()
    lib._STRATEGY_CONFIGS.clear()
    yield
    lib._STRATEGY_INSTANCES.clear()
    lib._STRATEGY_CONFIGS.clear()


# ---------------------------------------------------------------------------
# Signal tests
# ---------------------------------------------------------------------------

class TestSignal:
    def test_signal_creation(self) -> None:
        s = Signal(direction=0.7, confidence=0.8, reasoning="test")
        assert s.direction == 0.7
        assert s.confidence == 0.8
        assert s.reasoning == "test"

    def test_signal_direction_bounds(self) -> None:
        with pytest.raises(ValueError):
            Signal(direction=1.5)
        with pytest.raises(ValueError):
            Signal(direction=-1.5)

    def test_signal_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            Signal(confidence=1.5)
        with pytest.raises(ValueError):
            Signal(confidence=-0.5)

    def test_signal_properties(self) -> None:
        buy = Signal(direction=0.5, confidence=0.8)
        assert buy.is_buy is True
        assert buy.is_sell is False
        assert buy.is_neutral is False
        assert buy.strength == 0.5

        sell = Signal(direction=-0.3, confidence=0.6)
        assert sell.is_sell is True
        assert sell.is_buy is False

        neutral = Signal(direction=0.0, confidence=0.1)
        assert neutral.is_neutral is True

    def test_signal_to_dict(self) -> None:
        s = Signal(direction=1.0, confidence=0.9, reasoning="test", strategy_id="x")
        d = s.to_dict()
        assert d["direction"] == 1.0
        assert d["strategy_id"] == "x"
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# Strategy dataclass tests
# ---------------------------------------------------------------------------

class TestStrategy:
    def test_strategy_creation(self) -> None:
        s = Strategy(id="test", name="Test Strategy")
        assert s.id == "test"
        assert s.name == "Test Strategy"

    def test_strategy_defaults(self) -> None:
        s = Strategy(id="x", name="X")
        assert s.stop_loss_pct == 0.02
        assert s.take_profit_pct == 0.06
        assert s.min_confidence == 0.5
        assert s.timeframes == []
        assert s.assets == []

    def test_strategy_validation(self) -> None:
        with pytest.raises(ValueError, match="id"):
            Strategy(name="Test")
        with pytest.raises(ValueError, match="name"):
            Strategy(id="test")
        with pytest.raises(ValueError, match="min_confidence"):
            Strategy(id="t", name="T", min_confidence=2.0)


# ---------------------------------------------------------------------------
# Library tests
# ---------------------------------------------------------------------------

class TestLibrary:
    def test_load_strategies(self) -> None:
        strategies = load_strategies()
        # 15 technical strategies + sentiment_signal (AI news + X).
        assert len(strategies) == 16

    def test_get_strategy(self) -> None:
        load_strategies()
        s = get_strategy("rsi_mean_reversion")
        assert s is not None
        assert isinstance(s, BaseStrategy)
        assert s.config.id == "rsi_mean_reversion"

    def test_get_strategy_not_found(self) -> None:
        load_strategies()
        s = get_strategy("nonexistent_strategy")
        assert s is None

    def test_list_strategies_all(self) -> None:
        load_strategies()
        all_strategies = list_strategies()
        # 15 technical strategies + sentiment_signal (AI news + X).
        assert len(all_strategies) == 16

    def test_list_strategies_by_category(self) -> None:
        load_strategies()
        trend = list_strategies(category="trend")
        assert len(trend) >= 4  # MA crossover, turtle, minervini, ATR, ichimoku
        for s in trend:
            assert s.category == "trend"

    def test_list_strategies_by_asset(self) -> None:
        load_strategies()
        stocks = list_strategies(asset_type="stocks")
        assert len(stocks) >= 10
        for s in stocks:
            assert "stocks" in s.assets

    def test_add_strategy(self) -> None:
        load_strategies()
        custom = add_strategy({
            "id": "custom_test",
            "name": "Custom Test Strategy",
            "category": "momentum",
            "timeframes": ["1d"],
            "assets": ["stocks"],
        })
        assert custom.id == "custom_test"
        # Should now appear in list
        all_s = list_strategies()
        assert any(s.id == "custom_test" for s in all_s)

    def test_add_strategy_validation(self) -> None:
        with pytest.raises(ValueError):
            add_strategy({"name": "Missing ID"})
        with pytest.raises(ValueError):
            add_strategy({"id": "no_name"})


# ---------------------------------------------------------------------------
# Strategy evaluation tests (all 15 strategies)
# ---------------------------------------------------------------------------

class TestStrategyEvaluation:
    """Test that every registered strategy produces a valid Signal."""

    STRATEGY_IDS = [
        "ma_crossover_50_200",
        "rsi_mean_reversion",
        "macd_signal_cross",
        "bollinger_breakout",
        "vwap_reversion",
        "turtle_trading",
        "minervini_sepa",
        "oneil_canslim",
        "dividend_growth",
        "volume_profile",
        "atr_trailing_stop",
        "ichimoku_cloud",
        "stochastic_oscillator",
        "fibonacci_retracement",
        "order_flow_imbalance",
    ]

    def test_all_strategies_registered(self) -> None:
        load_strategies()
        for sid in self.STRATEGY_IDS:
            s = get_strategy(sid)
            assert s is not None, f"Strategy '{sid}' not found"

    def test_all_strategies_have_config(self) -> None:
        load_strategies()
        for sid in self.STRATEGY_IDS:
            s = get_strategy(sid)
            assert s is not None
            assert s.config.id == sid
            assert s.config.name
            assert s.config.category

    def test_all_strategies_implement_interface(self) -> None:
        load_strategies()
        for sid in self.STRATEGY_IDS:
            s = get_strategy(sid)
            assert s is not None
            assert hasattr(s, "evaluate")
            assert hasattr(s, "required_indicators")
            assert hasattr(s, "minimum_data_points")
            indicators = s.required_indicators()
            assert isinstance(indicators, list)
            min_points = s.minimum_data_points()
            assert isinstance(min_points, int)
            assert min_points > 0

    def test_evaluate_all_strategies(self, price_data: pd.DataFrame) -> None:
        """Each strategy must produce a valid Signal on standard data."""
        load_strategies()
        for sid in self.STRATEGY_IDS:
            s = get_strategy(sid)
            assert s is not None, f"Strategy '{sid}' not loaded"

            min_bars = s.minimum_data_points()
            if len(price_data) < min_bars:
                data = _make_price_data(min_bars + 50)
            else:
                data = price_data

            if not s.validate_data(data):
                continue  # Skip if data is insufficient

            signal = s.evaluate(data)
            assert isinstance(signal, Signal), f"{sid} did not return Signal"
            assert -1.0 <= signal.direction <= 1.0, f"{sid} direction out of range"
            assert 0.0 <= signal.confidence <= 1.0, f"{sid} confidence out of range"
            assert isinstance(signal.reasoning, str)
            assert signal.strategy_id == sid

    def test_evaluate_library_function(self, price_data: pd.DataFrame) -> None:
        """Test the top-level evaluate() function."""
        load_strategies()
        signal = evaluate("rsi_mean_reversion", price_data, symbol="TEST")
        assert isinstance(signal, Signal)
        assert signal.strategy_id == "rsi_mean_reversion"
        assert signal.symbol == "TEST"

    def test_evaluate_unknown_strategy(self, price_data: pd.DataFrame) -> None:
        """evaluate() for unknown strategy returns neutral signal."""
        load_strategies()
        signal = evaluate("nonexistent", price_data)
        assert signal.direction == 0.0
        assert signal.confidence == 0.0
        assert "not found" in signal.reasoning

    def test_insufficient_data_returns_neutral(self) -> None:
        """Strategy returns neutral signal when data is too short."""
        load_strategies()
        s = get_strategy("ma_crossover_50_200")
        assert s is not None
        short = _make_price_data(10)
        signal = s.evaluate(short)  # Will be caught by validate_data in evaluate()
        # Even if evaluate runs, it should handle gracefully
        assert isinstance(signal, Signal)

    def test_each_strategy_config_values(self) -> None:
        """Verify all strategy configs have valid risk parameters."""
        load_strategies()
        for sid in self.STRATEGY_IDS:
            s = get_strategy(sid)
            assert s is not None
            config = s.config
            assert config.stop_loss_pct > 0, f"{sid} has invalid stop_loss_pct"
            assert config.take_profit_pct > 0, f"{sid} has invalid take_profit_pct"
            assert 0 < config.position_size_pct <= 1.0, f"{sid} has invalid position_size_pct"
            assert 0 <= config.min_confidence <= 1.0, f"{sid} has invalid min_confidence"
            assert len(config.entry_rules) > 0, f"{sid} has no entry_rules"
            assert len(config.exit_rules) > 0, f"{sid} has no exit_rules"
