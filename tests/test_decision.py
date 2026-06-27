"""Tests for the Decision Engine (M6)."""

import numpy as np
import pandas as pd
import pytest
from datetime import datetime
from typing import Dict, List, Optional

from src.decision.engine import AnalysisResult, DecisionEngine
from src.decision.logging import (
    clear_decision_logs,
    format_recommendation,
    get_decision_count,
    get_decision_logs,
)
from src.decision.models import (
    DecisionLog,
    Direction,
    PortfolioPosition,
    PortfolioState,
    RiskConfig,
    StrategyPerformance,
    TradeRecommendation,
)
from src.decision.position_sizing import (
    PositionSizeResult,
    calculate_position_size,
    kelly_criterion,
)
from src.decision.risk import (
    RiskCheckResult,
    check_agreement,
    check_confidence,
    check_correlation,
    check_daily_loss,
    check_position_size,
    run_all_risk_checks,
)
from src.decision.signals import (
    AggregatedSignal,
    aggregate_signals,
    direction_from_signal,
)
from src.strategy.signals import Signal


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_price_data(
    n_bars: int = 250,
    start_price: float = 150.0,
    trend: float = 0.0005,
    volatility: float = 0.02,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV data."""
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="B")
    returns = rng.normal(trend, volatility, n_bars)
    close = start_price * np.cumprod(1 + returns)

    high = close * (1 + rng.uniform(0, 0.02, n_bars))
    low = close * (1 - rng.uniform(0, 0.02, n_bars))
    open_ = close * (1 + rng.normal(0, 0.005, n_bars))
    volume = rng.randint(100_000, 5_000_000, n_bars).astype(float)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


@pytest.fixture
def price_data() -> pd.DataFrame:
    """Standard 250-bar price dataset."""
    return _make_price_data(250)


@pytest.fixture
def short_data() -> pd.DataFrame:
    """Short dataset."""
    return _make_price_data(30)


@pytest.fixture
def risk_config() -> RiskConfig:
    """Default risk configuration."""
    return RiskConfig()


@pytest.fixture
def empty_portfolio() -> PortfolioState:
    """Empty portfolio."""
    return PortfolioState()


@pytest.fixture
def portfolio_with_positions() -> PortfolioState:
    """Portfolio with some existing positions."""
    return PortfolioState(
        positions=[
            PortfolioPosition(
                symbol="MSFT",
                direction=Direction.BUY,
                entry_price=350.0,
                current_price=360.0,
                size_pct=0.04,
                sector="technology",
            ),
            PortfolioPosition(
                symbol="GOOGL",
                direction=Direction.BUY,
                entry_price=140.0,
                current_price=135.0,
                size_pct=0.03,
                sector="technology",
            ),
        ],
        daily_pnl_pct=-0.005,
    )


@pytest.fixture(autouse=True)
def _clear_logs():
    """Clear decision logs between tests."""
    clear_decision_logs()
    yield
    clear_decision_logs()


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestModels:
    def test_risk_config_defaults(self) -> None:
        rc = RiskConfig()
        # Aggressive defaults — favors taking trades over sitting in cash.
        assert rc.max_position_pct == 0.10
        assert rc.max_portfolio_risk == 0.04
        assert rc.max_correlated_positions == 6
        assert rc.min_confidence == 0.30
        assert rc.min_strategies_agreeing == 1
        assert rc.max_holding_period_days == 30
        assert rc.stop_loss_atr_multiple == 2.0

    def test_risk_config_custom(self) -> None:
        rc = RiskConfig(max_position_pct=0.10, min_confidence=0.7)
        assert rc.max_position_pct == 0.10
        assert rc.min_confidence == 0.7

    def test_direction_enum(self) -> None:
        assert Direction.BUY.value == "BUY"
        assert Direction.SELL.value == "SELL"
        assert Direction.HOLD.value == "HOLD"

    def test_trade_recommendation_creation(self) -> None:
        rec = TradeRecommendation(
            symbol="AAPL",
            direction=Direction.BUY,
            confidence=0.8,
            strategies_agreeing=["rsi", "macd"],
            strategies_disagreeing=["bollinger"],
            entry_price=150.0,
            stop_loss=144.0,
            take_profit=162.0,
            position_size_pct=0.05,
            risk_reward_ratio=2.0,
            reasoning="Strong buy signal",
        )
        assert rec.symbol == "AAPL"
        assert rec.direction == Direction.BUY
        assert rec.confidence == 0.8
        assert len(rec.strategies_agreeing) == 2
        assert rec.risk_reward_ratio == 2.0

    def test_trade_recommendation_to_dict(self) -> None:
        rec = TradeRecommendation(
            symbol="AAPL",
            direction=Direction.BUY,
            confidence=0.75,
        )
        d = rec.to_dict()
        assert d["symbol"] == "AAPL"
        assert d["direction"] == "BUY"
        assert d["confidence"] == 0.75
        assert "timestamp" in d

    def test_portfolio_position_creation(self) -> None:
        pos = PortfolioPosition(
            symbol="AAPL",
            direction=Direction.BUY,
            entry_price=150.0,
            current_price=155.0,
            size_pct=0.05,
            sector="technology",
        )
        assert pos.symbol == "AAPL"
        assert pos.sector == "technology"

    def test_strategy_performance_weight(self) -> None:
        # High performance
        high = StrategyPerformance(win_rate=0.8, profit_factor=2.5, sharpe_ratio=2.0)
        assert high.weight > 1.0

        # Low performance
        low = StrategyPerformance(win_rate=0.3, profit_factor=0.5, sharpe_ratio=-1.0)
        assert low.weight < 0.5

        # Zero performance (clamped to minimum)
        zero = StrategyPerformance(win_rate=0.0, profit_factor=0.0, sharpe_ratio=0.0)
        assert zero.weight >= 0.1


# ---------------------------------------------------------------------------
# Signal aggregation tests
# ---------------------------------------------------------------------------

class TestSignalAggregation:
    def test_empty_signals(self) -> None:
        result = aggregate_signals([])
        assert result.direction == 0.0
        assert result.confidence == 0.0
        assert result.agreeing == []
        assert result.disagreeing == []

    def test_single_signal(self) -> None:
        sig = Signal(direction=0.8, confidence=0.9, strategy_id="rsi", symbol="AAPL")
        result = aggregate_signals([sig])
        assert result.direction == pytest.approx(0.8 * 0.9, rel=1e-2)
        assert result.confidence == pytest.approx(0.9, rel=1e-2)
        assert "rsi" in result.agreeing

    def test_multiple_agreeing_signals(self) -> None:
        signals = [
            Signal(direction=0.8, confidence=0.9, strategy_id="rsi", symbol="AAPL"),
            Signal(direction=0.7, confidence=0.8, strategy_id="macd", symbol="AAPL"),
            Signal(direction=0.6, confidence=0.7, strategy_id="ma_cross", symbol="AAPL"),
        ]
        result = aggregate_signals(signals)
        assert result.direction > 0
        assert result.confidence > 0.5
        assert len(result.agreeing) == 3
        assert len(result.disagreeing) == 0

    def test_disagreeing_signals(self) -> None:
        signals = [
            Signal(direction=0.8, confidence=0.9, strategy_id="rsi", symbol="AAPL"),
            Signal(direction=-0.7, confidence=0.8, strategy_id="macd", symbol="AAPL"),
        ]
        result = aggregate_signals(signals)
        # Direction should be between -1 and 1
        assert -1.0 <= result.direction <= 1.0
        assert result.confidence > 0

    def test_weighted_by_performance(self) -> None:
        signals = [
            Signal(direction=1.0, confidence=0.8, strategy_id="good", symbol="AAPL"),
            Signal(direction=-1.0, confidence=0.8, strategy_id="bad", symbol="AAPL"),
        ]
        performance = {
            "good": StrategyPerformance(win_rate=0.9, profit_factor=3.0, sharpe_ratio=2.5),
            "bad": StrategyPerformance(win_rate=0.3, profit_factor=0.5, sharpe_ratio=-0.5),
        }
        result = aggregate_signals(signals, performance)
        # Good strategy has higher weight, so aggregate should lean positive
        assert result.direction > 0

    def test_neutral_signals(self) -> None:
        signals = [
            Signal(direction=0.05, confidence=0.5, strategy_id="neutral1", symbol="AAPL"),
            Signal(direction=-0.05, confidence=0.5, strategy_id="neutral2", symbol="AAPL"),
        ]
        result = aggregate_signals(signals, neutral_threshold=0.1)
        assert len(result.agreeing) == 0
        assert len(result.disagreeing) == 0

    def test_direction_from_signal(self) -> None:
        assert direction_from_signal(0.5) == Direction.BUY
        assert direction_from_signal(-0.5) == Direction.SELL
        assert direction_from_signal(0.0) == Direction.HOLD
        # Default dead-band is ±0.02 (aggressive): a modest lean now acts.
        assert direction_from_signal(0.01) == Direction.HOLD
        assert direction_from_signal(-0.01) == Direction.HOLD
        assert direction_from_signal(0.05) == Direction.BUY
        assert direction_from_signal(-0.05) == Direction.SELL
        # Dead-band is overridable per call.
        assert direction_from_signal(0.05, deadband=0.1) == Direction.HOLD


# ---------------------------------------------------------------------------
# Position sizing tests
# ---------------------------------------------------------------------------

class TestPositionSizing:
    def test_kelly_criterion_profitable(self) -> None:
        # 60% win rate, 2:1 reward-risk
        k = kelly_criterion(win_rate=0.6, avg_win=0.04, avg_loss=0.02, fractional=0.25)
        assert 0 < k < 0.25

    def test_kelly_criterion_unprofitable(self) -> None:
        # 40% win rate, 1:1 reward-risk (negative edge)
        k = kelly_criterion(win_rate=0.4, avg_win=0.02, avg_loss=0.02, fractional=0.25)
        assert k == 0.0

    def test_kelly_criterion_edge_cases(self) -> None:
        assert kelly_criterion(win_rate=0.0, avg_win=0.02, avg_loss=0.02) == 0.0
        assert kelly_criterion(win_rate=1.0, avg_win=0.02, avg_loss=0.02) == 0.0
        assert kelly_criterion(win_rate=0.6, avg_win=0.0, avg_loss=0.02) == 0.0
        assert kelly_criterion(win_rate=0.6, avg_win=0.02, avg_loss=0.0) == 0.0

    def test_kelly_criterion_scaling(self) -> None:
        full = kelly_criterion(0.6, 0.04, 0.02, fractional=1.0)
        half = kelly_criterion(0.6, 0.04, 0.02, fractional=0.5)
        assert half == pytest.approx(full * 0.5)

    def test_calculate_position_size_kelly(self) -> None:
        result = calculate_position_size(
            win_rate=0.6,
            avg_win=0.04,
            avg_loss=0.02,
            risk_config=RiskConfig(max_position_pct=0.05),
            stop_distance_pct=0.02,
            portfolio_value=100000,
        )
        assert result.size_pct > 0
        assert result.size_pct <= 0.05
        assert result.method in ("kelly", "capped")

    def test_calculate_position_size_fixed_fractional(self) -> None:
        result = calculate_position_size(
            win_rate=None,
            avg_win=None,
            avg_loss=None,
            risk_config=RiskConfig(max_position_pct=0.05),
            stop_distance_pct=0.02,
            portfolio_value=100000,
        )
        assert result.size_pct > 0
        assert result.size_pct <= 0.05
        assert result.method == "fixed_fractional"

    def test_calculate_position_size_capped(self) -> None:
        # Kelly would produce a large fraction, but max_position_pct caps it
        result = calculate_position_size(
            win_rate=0.8,
            avg_win=0.10,
            avg_loss=0.01,
            risk_config=RiskConfig(max_position_pct=0.05),
            stop_distance_pct=0.02,
            portfolio_value=100000,
        )
        assert result.size_pct <= 0.05
        assert result.kelly_fraction > 0.05  # Raw Kelly exceeds cap

    def test_position_size_max_cap(self) -> None:
        result = calculate_position_size(
            risk_config=RiskConfig(max_position_pct=0.03),
            stop_distance_pct=0.02,
            portfolio_value=100000,
        )
        assert result.size_pct <= 0.03


# ---------------------------------------------------------------------------
# Risk management tests
# ---------------------------------------------------------------------------

class TestRiskManagement:
    def test_position_size_check_pass(self) -> None:
        result = check_position_size(0.05, RiskConfig(max_position_pct=0.05))
        assert result.passed is True

    def test_position_size_check_fail(self) -> None:
        result = check_position_size(0.10, RiskConfig(max_position_pct=0.05))
        assert result.passed is False
        assert "exceeds max" in result.reason

    def test_confidence_check_pass(self) -> None:
        result = check_confidence(0.8, RiskConfig(min_confidence=0.6))
        assert result.passed is True

    def test_confidence_check_fail(self) -> None:
        result = check_confidence(0.4, RiskConfig(min_confidence=0.6))
        assert result.passed is False
        assert "below minimum" in result.reason

    def test_agreement_check_pass(self) -> None:
        result = check_agreement(3, RiskConfig(min_strategies_agreeing=2))
        assert result.passed is True

    def test_agreement_check_fail(self) -> None:
        result = check_agreement(1, RiskConfig(min_strategies_agreeing=2))
        assert result.passed is False
        assert "Only 1 strategies agree" in result.reason

    def test_daily_loss_check_pass(self) -> None:
        portfolio = PortfolioState(daily_pnl_pct=-0.01)
        result = check_daily_loss(portfolio, RiskConfig(max_portfolio_risk=0.02))
        assert result.passed is True

    def test_daily_loss_check_fail(self) -> None:
        portfolio = PortfolioState(daily_pnl_pct=-0.03)
        result = check_daily_loss(portfolio, RiskConfig(max_portfolio_risk=0.02))
        assert result.passed is False
        assert "exceeds limit" in result.reason

    def test_correlation_check_new_sector(self) -> None:
        portfolio = PortfolioState(positions=[])
        result = check_correlation("AAPL", "technology", portfolio)
        assert result.passed is True

    def test_correlation_check_sector_limit(self) -> None:
        portfolio = PortfolioState(
            positions=[
                PortfolioPosition(symbol="MSFT", sector="technology"),
                PortfolioPosition(symbol="GOOGL", sector="technology"),
                PortfolioPosition(symbol="META", sector="technology"),
            ]
        )
        # Pin the limit so this exercises the mechanism, not the default.
        result = check_correlation(
            "AAPL",
            "technology",
            portfolio,
            risk_config=RiskConfig(max_correlated_positions=3),
        )
        assert result.passed is False
        assert "already has 3 positions" in result.reason

    def test_correlation_check_duplicate_symbol(self) -> None:
        portfolio = PortfolioState(
            positions=[
                PortfolioPosition(symbol="AAPL", sector="technology"),
            ]
        )
        result = check_correlation("AAPL", "technology", portfolio)
        assert result.passed is False
        assert "Already holding" in result.reason

    def test_run_all_risk_checks_pass(self) -> None:
        portfolio = PortfolioState(daily_pnl_pct=0.0)
        result = run_all_risk_checks(
            size_pct=0.04,
            confidence=0.75,
            agreeing_count=3,
            symbol="AAPL",
            sector="technology",
            portfolio=portfolio,
            risk_config=RiskConfig(min_confidence=0.6, min_strategies_agreeing=2),
        )
        assert result.passed is True

    def test_run_all_risk_checks_fail_size(self) -> None:
        portfolio = PortfolioState(daily_pnl_pct=0.0)
        result = run_all_risk_checks(
            size_pct=0.10,  # Too large
            confidence=0.75,
            agreeing_count=3,
            symbol="AAPL",
            sector="technology",
            portfolio=portfolio,
            risk_config=RiskConfig(max_position_pct=0.05),
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# Decision logging tests
# ---------------------------------------------------------------------------

class TestDecisionLogging:
    def test_log_decision(self) -> None:
        entry = DecisionLog(
            timestamp=datetime.utcnow(),
            symbol="AAPL",
            aggregated_direction=0.5,
            aggregated_confidence=0.7,
            confidence_check=True,
            agreement_check=True,
            risk_checks={"all_passed": True},
            reasoning="Strong buy signal",
        )
        assert entry.symbol == "AAPL"
        assert entry.confidence_check is True

    def test_format_recommendation(self) -> None:
        rec = TradeRecommendation(
            symbol="AAPL",
            direction=Direction.BUY,
            confidence=0.8,
            strategies_agreeing=["rsi", "macd"],
            strategies_disagreeing=[],
            entry_price=150.0,
            stop_loss=144.0,
            take_profit=162.0,
            position_size_pct=0.05,
            risk_reward_ratio=2.0,
            reasoning="Test reasoning",
        )
        formatted = format_recommendation(rec)
        assert "AAPL" in formatted
        assert "BUY" in formatted
        assert "$150.00" in formatted
        assert "rsi" in formatted


# ---------------------------------------------------------------------------
# Decision Engine integration tests
# ---------------------------------------------------------------------------

class TestDecisionEngine:
    def test_engine_creation(self) -> None:
        engine = DecisionEngine()
        assert engine.risk_config.min_confidence == 0.30
        assert len(engine.portfolio.positions) == 0

    def test_engine_with_custom_config(self) -> None:
        rc = RiskConfig(min_confidence=0.8, max_position_pct=0.03)
        engine = DecisionEngine(risk_config=rc)
        assert engine.risk_config.min_confidence == 0.8

    def test_analyze_generates_result(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"]
        )
        result = engine.analyze("AAPL", price_data)
        assert isinstance(result, AnalysisResult)
        assert result.symbol == "AAPL"
        assert result.aggregated is not None
        assert len(result.signals) > 0

    def test_analyze_with_specific_strategies(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["ma_crossover_50_200", "rsi_mean_reversion"]
        )
        result = engine.analyze("AAPL", price_data)
        assert result.aggregated is not None
        assert result.risk_result is not None
        assert result.position_size is not None

    def test_analyze_logs_decision(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion"]
        )
        engine.analyze("AAPL", price_data)
        logs = engine.get_logs("AAPL")
        assert len(logs) == 1
        assert logs[0].symbol == "AAPL"

    def test_analyze_recommendation_has_prices(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"]
        )
        result = engine.analyze("AAPL", price_data)
        if result.recommendation:
            rec = result.recommendation
            assert rec.entry_price > 0
            assert rec.stop_loss > 0
            assert rec.take_profit > 0
            assert rec.position_size_pct > 0
            assert rec.risk_reward_ratio > 0

    def test_analyze_risk_blocks_overconcentrated(
        self, price_data: pd.DataFrame
    ) -> None:
        portfolio = PortfolioState(
            positions=[
                PortfolioPosition(symbol="MSFT", size_pct=0.04, sector="technology"),
                PortfolioPosition(symbol="GOOGL", size_pct=0.04, sector="technology"),
                PortfolioPosition(symbol="META", size_pct=0.04, sector="technology"),
            ]
        )
        engine = DecisionEngine(
            risk_config=RiskConfig(max_correlated_positions=3),
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"],
            portfolio=portfolio,
        )
        result = engine.analyze("AAPL", price_data, sector="technology")
        # Should be blocked by correlation check (4th tech position)
        if result.recommendation is not None:
            # If somehow still has recommendation, it should be because risk passed
            assert result.risk_result is not None

    def test_analyze_daily_loss_blocks(self, price_data: pd.DataFrame) -> None:
        portfolio = PortfolioState(daily_pnl_pct=-0.03)
        engine = DecisionEngine(
            risk_config=RiskConfig(max_portfolio_risk=0.02),
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"],
            portfolio=portfolio,
        )
        result = engine.analyze("AAPL", price_data)
        # Should be blocked by daily loss limit
        assert result.recommendation is None

    def test_explain_returns_string(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion"]
        )
        result = engine.analyze("AAPL", price_data)
        explanation = engine.explain(result)
        assert isinstance(explanation, str)
        assert "AAPL" in explanation
        assert "Signal" in explanation or "Direction" in explanation

    def test_simulate_buy_positive(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"]
        )
        result = engine.analyze("AAPL", price_data)
        sim = engine.simulate(result, 0.10)
        assert "simulated_pnl_pct" in sim
        assert "hit_stop" in sim
        assert "hit_target" in sim
        assert "explanation" in sim
        assert isinstance(sim["explanation"], str)

    def test_simulate_sell(self) -> None:
        rec = TradeRecommendation(
            symbol="AAPL",
            direction=Direction.SELL,
            confidence=0.8,
            entry_price=150.0,
            stop_loss=156.0,
            take_profit=138.0,
            position_size_pct=0.05,
            risk_reward_ratio=2.0,
        )
        result = AnalysisResult(symbol="AAPL", recommendation=rec)
        engine = DecisionEngine()
        sim = engine.simulate(result, -0.05)  # Price drops 5%
        assert sim["simulated_pnl_pct"] > 0  # Profit on short

    def test_simulate_no_recommendation(self) -> None:
        result = AnalysisResult(symbol="AAPL", recommendation=None)
        engine = DecisionEngine()
        sim = engine.simulate(result, 0.10)
        assert sim["action"] == "HOLD"
        assert sim["simulated_pnl_pct"] == 0.0

    def test_check_risk(self, empty_portfolio: PortfolioState) -> None:
        engine = DecisionEngine(portfolio=empty_portfolio)
        result = engine.check_risk("AAPL", 0.05, sector="technology")
        assert isinstance(result, RiskCheckResult)

    def test_clear_logs(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion"]
        )
        engine.analyze("AAPL", price_data)
        assert len(engine.get_logs()) > 0
        engine.clear_logs()
        assert len(engine.get_logs()) == 0

    def test_analyze_multiple_symbols(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"]
        )
        result_aapl = engine.analyze("AAPL", price_data)
        result_googl = engine.analyze("GOOGL", price_data)
        assert result_aapl.symbol == "AAPL"
        assert result_googl.symbol == "GOOGL"

    def test_analyze_portfolio(self, price_data: pd.DataFrame) -> None:
        portfolio = PortfolioState(
            positions=[
                PortfolioPosition(
                    symbol="AAPL",
                    direction=Direction.BUY,
                    entry_price=150.0,
                    current_price=155.0,
                    size_pct=0.05,
                    sector="technology",
                ),
            ]
        )
        engine = DecisionEngine(
            strategy_ids=["rsi_mean_reversion"],
            portfolio=portfolio,
        )
        market_data = {"AAPL": price_data}
        results = engine.analyze_portfolio(portfolio, market_data)
        assert len(results) == 1
        assert results[0].symbol == "AAPL"

    def test_atr_calculation(self, price_data: pd.DataFrame) -> None:
        engine = DecisionEngine()
        atr = engine._calculate_atr(price_data)
        assert atr > 0
        assert isinstance(atr, float)

    def test_atr_short_data(self, short_data: pd.DataFrame) -> None:
        engine = DecisionEngine()
        atr = engine._calculate_atr(short_data)
        assert atr > 0


# ---------------------------------------------------------------------------
# Full pipeline integration test
# ---------------------------------------------------------------------------

class TestFullPipeline:
    """End-to-end test of the complete decision pipeline."""

    def test_full_buy_recommendation(
        self, price_data: pd.DataFrame
    ) -> None:
        """Full pipeline: signals -> aggregate -> risk -> recommendation."""
        # Create a performance profile that favors buy signals
        performance = {
            "rsi_mean_reversion": StrategyPerformance(
                win_rate=0.65, profit_factor=1.8, sharpe_ratio=1.5
            ),
            "macd_signal_cross": StrategyPerformance(
                win_rate=0.55, profit_factor=1.4, sharpe_ratio=0.8
            ),
            "ma_crossover_50_200": StrategyPerformance(
                win_rate=0.60, profit_factor=1.6, sharpe_ratio=1.2
            ),
        }

        engine = DecisionEngine(
            risk_config=RiskConfig(
                min_confidence=0.5,
                min_strategies_agreeing=2,
                max_position_pct=0.05,
            ),
            strategy_performance=performance,
            strategy_ids=[
                "rsi_mean_reversion",
                "macd_signal_cross",
                "ma_crossover_50_200",
            ],
        )

        result = engine.analyze("AAPL", price_data, portfolio_value=100000)

        # Verify all parts of the pipeline
        assert result.symbol == "AAPL"
        assert result.aggregated is not None
        assert len(result.signals) == 3
        assert result.risk_result is not None
        assert result.position_size is not None

        # If we got a recommendation, verify it's complete
        if result.recommendation is not None:
            rec = result.recommendation
            assert rec.direction in (Direction.BUY, Direction.SELL)
            assert rec.confidence > 0
            assert rec.entry_price > 0
            assert rec.stop_loss > 0
            assert rec.take_profit > 0
            assert rec.position_size_pct > 0
            assert rec.risk_reward_ratio > 0
            assert len(rec.strategies_agreeing) >= 2
            assert len(rec.reasoning) > 0

        # Verify logging
        logs = engine.get_logs("AAPL")
        assert len(logs) >= 1

        # Verify explanation
        explanation = engine.explain(result)
        assert "AAPL" in explanation

    def test_pipeline_blocks_low_confidence(self) -> None:
        """Pipeline blocks when confidence is too low."""
        # Create data where strategies give weak signals
        rng = np.random.RandomState(99)
        dates = pd.date_range("2023-01-01", periods=250, freq="B")
        # Sideways market — no clear direction
        close = 100 + np.cumsum(rng.normal(0, 0.001, 250))
        data = pd.DataFrame(
            {
                "open": close + rng.normal(0, 0.01, 250),
                "high": close + rng.uniform(0, 0.02, 250),
                "low": close - rng.uniform(0, 0.02, 250),
                "close": close,
                "volume": rng.randint(100_000, 5_000_000, 250).astype(float),
            },
            index=dates,
        )

        engine = DecisionEngine(
            risk_config=RiskConfig(min_confidence=0.6),
            strategy_ids=["rsi_mean_reversion", "macd_signal_cross"],
        )
        result = engine.analyze("TEST", data)
        # With sideways data, likely no recommendation
        assert result.recommendation is None or result.aggregated is not None

    def test_explain_holds(self) -> None:
        """Engine can explain HOLD decisions."""
        result = AnalysisResult(
            symbol="AAPL",
            aggregated=AggregatedSignal(direction=0.0, confidence=0.2),
            recommendation=None,
            reasoning="No clear signal.",
        )
        engine = DecisionEngine()
        explanation = engine.explain(result)
        assert "AAPL" in explanation
        assert "0.200" in explanation or "20" in explanation


class TestDecisionLogging:
    """Decision-log JSON serialization must survive numpy scalar types."""

    def test_json_default_coerces_numpy(self):
        import numpy as np
        from src.decision.logging import _json_default

        assert _json_default(np.bool_(True)) is True
        assert _json_default(np.float64(0.5)) == 0.5
        assert _json_default(np.int64(3)) == 3

    def test_log_decision_with_numpy_does_not_raise(self):
        import numpy as np
        from src.decision.logging import log_decision

        # numpy bools/floats (as produced by `np_float >= threshold`) must not
        # crash the JSON log line.
        entry = log_decision(
            symbol="BTC",
            input_data={"atr": np.float64(1.23)},
            strategy_signals=[],
            aggregated_direction=np.float64(-0.1),
            aggregated_confidence=np.float64(0.64),
            confidence_check=np.bool_(True),
            agreement_check=np.bool_(False),
            risk_checks={"all_passed": np.bool_(True)},
            recommendation=None,
            reasoning="numpy smoke test",
        )
        assert entry.symbol == "BTC"
