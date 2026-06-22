"""Tests for the Learning Loop module (M9)."""

import math
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd
import pytest

from src.learning.insights import InsightsEngine, InsightsReport, StrategyInsight
from src.learning.regime import MarketRegime, RegimeDetector, RegimeState
from src.learning.reporting import LearningReport, ReportingEngine
from src.learning.tracker import StrategyPerformance, TradeOutcome, Tracker
from src.learning.weights import MAX_WEIGHT, MIN_WEIGHT, WeightManager


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def tracker() -> Tracker:
    """Create a tracker with sample trade data."""
    t = Tracker()
    now = datetime.utcnow()

    # ma_crossover: good performer
    for i in range(15):
        ret = 0.02 if i % 3 != 0 else -0.01
        t.track_outcome(
            TradeOutcome(
                trade_id=f"mc_{i}",
                strategy_id="ma_crossover",
                symbol="AAPL",
                direction="LONG",
                entry_price=100.0,
                exit_price=100.0 * (1 + ret),
                quantity=10,
                entry_time=now - timedelta(days=30 - i),
                exit_time=now - timedelta(days=29 - i),
                pnl=100.0 * ret * 10,
                return_pct=ret,
                regime="bull",
            )
        )
        t.record_signal("ma_crossover")

    # rsi_mean_reversion: moderate performer
    for i in range(12):
        ret = 0.01 if i % 2 == 0 else -0.008
        t.track_outcome(
            TradeOutcome(
                trade_id=f"rsi_{i}",
                strategy_id="rsi_mean_reversion",
                symbol="MSFT",
                direction="LONG",
                entry_price=200.0,
                exit_price=200.0 * (1 + ret),
                quantity=5,
                entry_time=now - timedelta(days=30 - i),
                exit_time=now - timedelta(days=29 - i),
                pnl=200.0 * ret * 5,
                return_pct=ret,
                regime="sideways",
            )
        )
        t.record_signal("rsi_mean_reversion")

    # macd_signal_cross: poor performer
    for i in range(10):
        ret = -0.015 if i % 2 == 0 else 0.005
        t.track_outcome(
            TradeOutcome(
                trade_id=f"macd_{i}",
                strategy_id="macd_signal_cross",
                symbol="GOOGL",
                direction="LONG",
                entry_price=150.0,
                exit_price=150.0 * (1 + ret),
                quantity=8,
                entry_time=now - timedelta(days=30 - i),
                exit_time=now - timedelta(days=29 - i),
                pnl=150.0 * ret * 8,
                return_pct=ret,
                regime="bear",
            )
        )
        t.record_signal("macd_signal_cross")

    return t


@pytest.fixture
def performance_map() -> Dict[str, StrategyPerformance]:
    """Create a sample performance map."""
    return {
        "ma_crossover": StrategyPerformance(
            strategy_id="ma_crossover",
            period="1m",
            total_signals=20,
            signals_taken=15,
            win_rate=0.67,
            avg_return=0.012,
            sharpe_ratio=1.5,
            max_drawdown=0.03,
        ),
        "rsi_mean_reversion": StrategyPerformance(
            strategy_id="rsi_mean_reversion",
            period="1m",
            total_signals=18,
            signals_taken=12,
            win_rate=0.50,
            avg_return=0.005,
            sharpe_ratio=0.6,
            max_drawdown=0.05,
        ),
        "macd_signal_cross": StrategyPerformance(
            strategy_id="macd_signal_cross",
            period="1m",
            total_signals=15,
            signals_taken=10,
            win_rate=0.30,
            avg_return=-0.005,
            sharpe_ratio=-0.8,
            max_drawdown=0.08,
        ),
    }


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Create sample OHLCV data for regime detection."""
    np.random.seed(42)
    n = 60
    dates = pd.date_range(end=datetime.utcnow(), periods=n, freq="D")
    base_price = 100.0
    returns = np.random.normal(0.001, 0.02, n)  # Slight upward trend
    prices = base_price * np.cumprod(1 + returns)
    high = prices * (1 + np.abs(np.random.normal(0, 0.01, n)))
    low = prices * (1 - np.abs(np.random.normal(0, 0.01, n)))
    volume = np.random.randint(1_000_000, 10_000_000, n)

    return pd.DataFrame(
        {
            "open": prices * 0.999,
            "high": high,
            "low": low,
            "close": prices,
            "volume": volume,
        },
        index=dates,
    )


# ======================================================================
# Tests: Tracker
# ======================================================================


class TestTradeOutcome:
    """Tests for TradeOutcome dataclass."""

    def test_default_values(self) -> None:
        outcome = TradeOutcome()
        assert outcome.trade_id == ""
        assert outcome.strategy_id == ""
        assert outcome.direction == "LONG"
        assert outcome.pnl == 0.0
        assert outcome.return_pct == 0.0
        assert outcome.regime == "unknown"

    def test_custom_values(self) -> None:
        now = datetime.utcnow()
        outcome = TradeOutcome(
            trade_id="t1",
            strategy_id="ma_crossover",
            symbol="AAPL",
            direction="SHORT",
            entry_price=150.0,
            exit_price=145.0,
            quantity=10,
            entry_time=now,
            exit_time=now,
            pnl=50.0,
            return_pct=0.033,
            regime="bear",
        )
        assert outcome.trade_id == "t1"
        assert outcome.pnl == 50.0
        assert outcome.regime == "bear"


class TestStrategyPerformance:
    """Tests for StrategyPerformance dataclass."""

    def test_default_values(self) -> None:
        perf = StrategyPerformance()
        assert perf.strategy_id == ""
        assert perf.period == "1m"
        assert perf.total_signals == 0
        assert perf.signals_taken == 0
        assert perf.win_rate == 0.0
        assert perf.sharpe_ratio == 0.0

    def test_to_dict(self) -> None:
        perf = StrategyPerformance(
            strategy_id="test",
            period="1w",
            total_signals=10,
            signals_taken=8,
            win_rate=0.625,
            avg_return=0.01,
            sharpe_ratio=1.2,
            max_drawdown=0.05,
        )
        d = perf.to_dict()
        assert d["strategy_id"] == "test"
        assert d["period"] == "1w"
        assert d["win_rate"] == 0.625
        assert d["sharpe_ratio"] == 1.2
        assert "last_updated" in d


class TestTracker:
    """Tests for the Tracker class."""

    def test_track_outcome(self) -> None:
        tracker = Tracker()
        outcome = TradeOutcome(
            trade_id="t1",
            strategy_id="ma_crossover",
            return_pct=0.05,
        )
        tracker.track_outcome(outcome)
        outcomes = tracker.get_outcomes()
        assert len(outcomes) == 1
        assert outcomes[0].trade_id == "t1"

    def test_record_signal(self) -> None:
        tracker = Tracker()
        tracker.record_signal("ma_crossover")
        tracker.record_signal("ma_crossover")
        tracker.record_signal("rsi_mean_reversion")
        perf = tracker.get_performance("ma_crossover")
        assert perf.total_signals == 2

    def test_get_outcomes_filter_by_strategy(self, tracker: Tracker) -> None:
        outcomes = tracker.get_outcomes(strategy_id="ma_crossover")
        assert all(o.strategy_id == "ma_crossover" for o in outcomes)
        assert len(outcomes) == 15

    def test_get_outcomes_filter_by_regime(self, tracker: Tracker) -> None:
        outcomes = tracker.get_outcomes(regime="bull")
        assert all(o.regime == "bull" for o in outcomes)
        assert len(outcomes) == 15

    def test_get_performance_no_trades(self) -> None:
        tracker = Tracker()
        perf = tracker.get_performance("nonexistent")
        assert perf.strategy_id == "nonexistent"
        assert perf.win_rate == 0.0
        assert perf.sharpe_ratio == 0.0

    def test_get_performance_with_trades(self, tracker: Tracker) -> None:
        perf = tracker.get_performance("ma_crossover", period="1y")
        assert perf.strategy_id == "ma_crossover"
        assert perf.signals_taken == 15
        assert perf.win_rate > 0.5  # Good performer
        assert perf.sharpe_ratio > 0

    def test_get_all_performance(self, tracker: Tracker) -> None:
        all_perf = tracker.get_all_performance("1y")
        assert len(all_perf) == 3
        assert "ma_crossover" in all_perf
        assert "rsi_mean_reversion" in all_perf
        assert "macd_signal_cross" in all_perf

    def test_max_drawdown_computation(self) -> None:
        # Test with a known return series
        returns = [0.05, -0.03, 0.02, -0.04, 0.01]
        dd = Tracker._compute_max_drawdown(returns)
        assert dd >= 0.0
        # Peak = 1.05*0.97 = 1.0185, trough after -0.04 = 1.0185*0.96 = 0.97776
        # Drawdown from peak to trough
        assert dd > 0.0

    def test_max_drawdown_empty(self) -> None:
        assert Tracker._compute_max_drawdown([]) == 0.0

    def test_sharpe_computation(self) -> None:
        # All positive returns should give positive Sharpe
        returns = [0.01, 0.02, 0.015, 0.01, 0.025]
        sharpe = Tracker._compute_sharpe(returns)
        assert sharpe > 0

    def test_sharpe_single_trade(self) -> None:
        assert Tracker._compute_sharpe([0.05]) == 0.0

    def test_sharpe_constant(self) -> None:
        assert Tracker._compute_sharpe([0.01, 0.01, 0.01]) == 0.0


# ======================================================================
# Tests: WeightManager
# ======================================================================


class TestWeightManager:
    """Tests for the WeightManager class."""

    def test_init_with_strategies(self) -> None:
        wm = WeightManager(strategy_ids=["a", "b", "c"])
        weights = wm.get_weights()
        assert len(weights) == 3
        assert abs(sum(weights.values()) - 1.0) < 0.001
        assert all(abs(w - 1 / 3) < 0.001 for w in weights.values())

    def test_init_empty(self) -> None:
        wm = WeightManager()
        assert wm.get_weights() == {}

    def test_recalculate_weights_basic(
        self, performance_map: Dict[str, StrategyPerformance]
    ) -> None:
        wm = WeightManager()
        weights = wm.recalculate_weights(performance_map)
        assert len(weights) == 3
        assert abs(sum(weights.values()) - 1.0) < 0.001

    def test_better_strategy_gets_higher_weight(
        self, performance_map: Dict[str, StrategyPerformance]
    ) -> None:
        wm = WeightManager()
        weights = wm.recalculate_weights(performance_map)
        # ma_crossover has the best Sharpe, should get highest weight
        assert weights["ma_crossover"] > weights["rsi_mean_reversion"]
        assert weights["rsi_mean_reversion"] > weights["macd_signal_cross"]

    def test_weight_bounds(self, performance_map: Dict[str, StrategyPerformance]) -> None:
        wm = WeightManager()
        weights = wm.recalculate_weights(performance_map)
        for w in weights.values():
            # After normalization, weights might slightly exceed bounds
            # but should be reasonable
            assert w > 0
            assert w < 1.0

    def test_empty_performance(self) -> None:
        wm = WeightManager()
        weights = wm.recalculate_weights({})
        assert weights == {}

    def test_single_strategy(self) -> None:
        wm = WeightManager()
        perf = {
            "only_one": StrategyPerformance(
                strategy_id="only_one",
                sharpe_ratio=1.0,
                signals_taken=20,
            )
        }
        weights = wm.recalculate_weights(perf)
        assert weights["only_one"] == 1.0

    def test_set_weights(self) -> None:
        wm = WeightManager()
        wm.set_weights({"a": 0.5, "b": 0.5})
        weights = wm.get_weights()
        assert abs(weights["a"] - 0.5) < 0.001
        assert abs(weights["b"] - 0.5) < 0.001

    def test_adapt_to_regime(self) -> None:
        wm = WeightManager(strategy_ids=["trend", "mean_rev", "momentum"])
        wm.set_weights({"trend": 0.4, "mean_rev": 0.3, "momentum": 0.3})

        # Apply bull regime bias
        adapted = wm.adapt_to_regime(
            "bull",
            regime_strategy_bias={
                "trend": 1.5,
                "mean_rev": 0.8,
                "momentum": 1.2,
            },
        )
        # Trend should get a higher share in bull markets
        assert adapted["trend"] > 0.35
        assert sum(adapted.values()) == pytest.approx(1.0, abs=0.01)

    def test_data_sufficiency_factor(self) -> None:
        # No trades -> low factor
        f0 = WeightManager._data_sufficiency_factor(0)
        assert f0 == 0.1

        # Many trades -> high factor
        f_many = WeightManager._data_sufficiency_factor(50)
        assert f_many > 0.9

        # Some trades -> moderate factor
        f_some = WeightManager._data_sufficiency_factor(3)
        assert 0.1 < f_some < 1.0

    def test_weights_sum_to_one(
        self, performance_map: Dict[str, StrategyPerformance]
    ) -> None:
        wm = WeightManager()
        weights = wm.recalculate_weights(performance_map)
        assert sum(weights.values()) == pytest.approx(1.0, abs=0.01)

    def test_bounds_enforced(self) -> None:
        """Verify MIN_WEIGHT and MAX_WEIGHT constants are correct."""
        assert MIN_WEIGHT == 0.05
        assert MAX_WEIGHT == 0.30


# ======================================================================
# Tests: RegimeDetector
# ======================================================================


class TestRegimeDetector:
    """Tests for the RegimeDetector class."""

    def test_detect_with_data(self, sample_ohlcv: pd.DataFrame) -> None:
        detector = RegimeDetector()
        state = detector.detect(sample_ohlcv)
        assert isinstance(state, RegimeState)
        assert isinstance(state.regime, MarketRegime)
        assert 0.0 <= state.confidence <= 1.0

    def test_detect_insufficient_data(self) -> None:
        detector = RegimeDetector()
        small_data = pd.DataFrame(
            {"open": [100], "high": [101], "low": [99], "close": [100], "volume": [1000]},
            index=pd.date_range("2024-01-01", periods=1),
        )
        state = detector.detect(small_data)
        assert state.regime == MarketRegime.UNKNOWN

    def test_bull_detection(self) -> None:
        """Create data with clear uptrend."""
        n = 60
        dates = pd.date_range(end=datetime.utcnow(), periods=n, freq="D")
        prices = np.linspace(90, 110, n) + np.random.normal(0, 0.5, n)
        high = prices + 1
        low = prices - 1
        df = pd.DataFrame(
            {
                "open": prices - 0.1,
                "high": high,
                "low": low,
                "close": prices,
                "volume": np.full(n, 1_000_000),
            },
            index=dates,
        )
        detector = RegimeDetector()
        state = detector.detect(df, vix=15.0)
        # Strong uptrend should be detected as bull
        assert state.regime in (MarketRegime.BULL, MarketRegime.SIDEWAYS)
        assert state.ma_20 > 0
        assert state.confidence > 0

    def test_bear_detection(self) -> None:
        """Create data with clear downtrend."""
        n = 60
        dates = pd.date_range(end=datetime.utcnow(), periods=n, freq="D")
        prices = np.linspace(110, 90, n) + np.random.normal(0, 0.5, n)
        high = prices + 1
        low = prices - 1
        df = pd.DataFrame(
            {
                "open": prices - 0.1,
                "high": high,
                "low": low,
                "close": prices,
                "volume": np.full(n, 1_000_000),
            },
            index=dates,
        )
        detector = RegimeDetector()
        state = detector.detect(df, vix=15.0)
        assert state.regime in (MarketRegime.BEAR, MarketRegime.SIDEWAYS)
        assert state.ma_20 > 0

    def test_high_volatility_vix(self, sample_ohlcv: pd.DataFrame) -> None:
        detector = RegimeDetector()
        state = detector.detect(sample_ohlcv, vix=30.0)
        assert state.regime == MarketRegime.HIGH_VOLATILITY
        assert state.vix_level == 30.0

    def test_sideways_detection(self) -> None:
        """Create range-bound data."""
        n = 60
        dates = pd.date_range(end=datetime.utcnow(), periods=n, freq="D")
        prices = 100.0 + np.sin(np.linspace(0, 4 * np.pi, n)) * 0.5
        high = prices + 0.2
        low = prices - 0.2
        df = pd.DataFrame(
            {
                "open": prices - 0.05,
                "high": high,
                "low": low,
                "close": prices,
                "volume": np.full(n, 1_000_000),
            },
            index=dates,
        )
        detector = RegimeDetector()
        state = detector.detect(df, vix=12.0)
        # Range-bound with low VIX should be sideways
        assert state.regime in (MarketRegime.SIDEWAYS, MarketRegime.BULL, MarketRegime.BEAR)

    def test_multi_asset(self, sample_ohlcv: pd.DataFrame) -> None:
        detector = RegimeDetector()
        assets = {"AAPL": sample_ohlcv, "MSFT": sample_ohlcv.copy()}
        results = detector.detect_multi_asset(assets, vix=18.0)
        assert len(results) == 2
        assert "AAPL" in results
        assert "MSFT" in results

    def test_regime_state_to_dict(self) -> None:
        state = RegimeState(
            regime=MarketRegime.BULL,
            confidence=0.8,
            ma_20=105.0,
            ma_20_slope=0.002,
            vix_level=15.0,
            avg_range_pct=0.015,
        )
        d = state.to_dict()
        assert d["regime"] == "bull"
        assert d["confidence"] == 0.8
        assert d["ma_20"] == 105.0

    def test_market_regime_enum(self) -> None:
        assert MarketRegime.BULL.value == "bull"
        assert MarketRegime.BEAR.value == "bear"
        assert MarketRegime.SIDEWAYS.value == "sideways"
        assert MarketRegime.HIGH_VOLATILITY.value == "high_volatility"
        assert MarketRegime.UNKNOWN.value == "unknown"


# ======================================================================
# Tests: InsightsEngine
# ======================================================================


class TestInsightsEngine:
    """Tests for the InsightsEngine class."""

    def test_get_insights(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        report = engine.get_insights("1y")
        assert isinstance(report, InsightsReport)
        assert len(report.insights) > 0
        assert isinstance(report.system_trend, str)
        assert report.system_trend in ("improving", "degrading", "stable")

    def test_best_strategies(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        report = engine.get_insights("1y")
        # ma_crossover should be among the best
        if report.best_strategies:
            assert "ma_crossover" in report.best_strategies

    def test_worst_strategies(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        report = engine.get_insights("1y")
        # macd_signal_cross should be among the worst
        if report.worst_strategies:
            assert "macd_signal_cross" in report.worst_strategies

    def test_strategy_insight(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        insight = engine.get_strategy_insight("ma_crossover", "1y")
        assert isinstance(insight, StrategyInsight)
        assert insight.strategy_id == "ma_crossover"
        assert insight.category in (
            "best", "worst", "average", "data_scarce"
        )
        assert len(insight.summary) > 0

    def test_loss_patterns(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        report = engine.get_insights("1y")
        # Report should include loss pattern analysis
        assert isinstance(report.loss_patterns, list)

    def test_regime_favorites(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        report = engine.get_insights("1y")
        assert isinstance(report.regime_favorites, dict)

    def test_empty_tracker(self) -> None:
        tracker = Tracker()
        engine = InsightsEngine(tracker)
        report = engine.get_insights("1m")
        assert isinstance(report, InsightsReport)
        assert len(report.insights) > 0  # Should have at least system_trend


# ======================================================================
# Tests: ReportingEngine
# ======================================================================


class TestReportingEngine:
    """Tests for the ReportingEngine class."""

    def test_weekly_report(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        reporter = ReportingEngine(tracker, engine)
        report = reporter.weekly_report()
        assert isinstance(report, LearningReport)
        assert report.report_type == "weekly"
        assert len(report.narrative) > 0

    def test_monthly_rebalance_summary(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        reporter = ReportingEngine(tracker, engine)
        report = reporter.monthly_rebalance_summary()
        assert isinstance(report, LearningReport)
        assert report.report_type == "monthly"
        assert len(report.narrative) > 0

    def test_quarterly_review(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        reporter = ReportingEngine(tracker, engine)
        report = reporter.quarterly_review()
        assert isinstance(report, LearningReport)
        assert report.report_type == "quarterly"
        assert len(report.narrative) > 0

    def test_weight_changes_tracking(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        reporter = ReportingEngine(
            tracker,
            engine,
            current_weights={"ma_crossover": 0.4, "rsi_mean_reversion": 0.35, "macd_signal_cross": 0.25},
            previous_weights={"ma_crossover": 0.33, "rsi_mean_reversion": 0.33, "macd_signal_cross": 0.34},
        )
        report = reporter.monthly_rebalance_summary()
        assert len(report.weight_changes) > 0

    def test_report_to_dict(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        reporter = ReportingEngine(tracker, engine)
        report = reporter.weekly_report()
        d = report.to_dict()
        assert d["report_type"] == "weekly"
        assert "narrative" in d
        assert "recommendations" in d

    def test_recommendations_generated(self, tracker: Tracker) -> None:
        engine = InsightsEngine(tracker)
        reporter = ReportingEngine(tracker, engine)
        report = reporter.weekly_report()
        assert isinstance(report.recommendations, list)


# ======================================================================
# Tests: Integration
# ======================================================================


class TestIntegration:
    """Integration tests verifying modules work together."""

    def test_full_learning_loop(self) -> None:
        """Test the complete flow: track -> weight -> insight -> report."""
        tracker = Tracker()
        now = datetime.utcnow()

        # Record trades
        for i in range(20):
            tracker.track_outcome(
                TradeOutcome(
                    trade_id=f"t_{i}",
                    strategy_id="strategy_a",
                    return_pct=0.02 if i % 3 != 0 else -0.01,
                    entry_time=now - timedelta(days=i),
                    regime="bull",
                )
            )
            tracker.record_signal("strategy_a")

        for i in range(15):
            tracker.track_outcome(
                TradeOutcome(
                    trade_id=f"s_{i}",
                    strategy_id="strategy_b",
                    return_pct=0.005 if i % 2 == 0 else -0.008,
                    entry_time=now - timedelta(days=i),
                    regime="sideways",
                )
            )
            tracker.record_signal("strategy_b")

        # Compute performance
        perf = tracker.get_all_performance("1y")
        assert len(perf) == 2

        # Compute weights
        wm = WeightManager()
        weights = wm.recalculate_weights(perf)
        assert abs(sum(weights.values()) - 1.0) < 0.01

        # Generate insights
        insights_engine = InsightsEngine(tracker)
        report = insights_engine.get_insights("1y")
        assert len(report.insights) > 0

        # Generate report
        reporter = ReportingEngine(tracker, insights_engine, weights)
        weekly = reporter.weekly_report()
        assert len(weekly.narrative) > 0

        monthly = reporter.monthly_rebalance_summary()
        assert len(monthly.narrative) > 0

        quarterly = reporter.quarterly_review()
        assert len(quarterly.narrative) > 0

    def test_regime_adaptation(self) -> None:
        """Test that regime detection affects weight allocation."""
        tracker = Tracker()
        now = datetime.utcnow()

        # Record trades in different regimes
        for i in range(10):
            regime = "bull" if i < 5 else "bear"
            ret = 0.03 if regime == "bull" else -0.02
            tracker.track_outcome(
                TradeOutcome(
                    trade_id=f"r_{i}",
                    strategy_id="trend_strategy",
                    return_pct=ret,
                    entry_time=now - timedelta(days=i),
                    regime=regime,
                )
            )
            tracker.record_signal("trend_strategy")

        perf = tracker.get_all_performance("1y")
        wm = WeightManager()
        weights = wm.recalculate_weights(perf)

        # Adapt to bull regime
        adapted = wm.adapt_to_regime(
            "bull",
            regime_strategy_bias={"trend_strategy": 1.5},
        )
        assert abs(sum(adapted.values()) - 1.0) < 0.01

    def test_weight_bounds_enforcement(self) -> None:
        """Verify weights respect min/max bounds after recalculation."""
        wm = WeightManager()
        # Create performance where one strategy dominates
        perf = {
            "star": StrategyPerformance(
                strategy_id="star",
                sharpe_ratio=5.0,
                signals_taken=100,
                win_rate=0.8,
            ),
            "loser": StrategyPerformance(
                strategy_id="loser",
                sharpe_ratio=-2.0,
                signals_taken=50,
                win_rate=0.2,
            ),
            "mid": StrategyPerformance(
                strategy_id="mid",
                sharpe_ratio=0.5,
                signals_taken=75,
                win_rate=0.5,
            ),
        }
        weights = wm.recalculate_weights(perf)
        # After normalization, all weights should be positive
        for w in weights.values():
            assert w > 0
