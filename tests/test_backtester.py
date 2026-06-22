"""Tests for the backtesting engine (M4).

Uses synthetic OHLCV data so tests run offline and fast.
"""

import math
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from src.strategy.backtester import (
    BacktestResult,
    Backtester,
    CommissionConfig,
    Trade,
)
from src.strategy.base import BaseStrategy, Strategy
from src.strategy.metrics import (
    annualized_return,
    avg_win_loss,
    calmar_ratio,
    daily_returns,
    expectancy,
    max_drawdown,
    monthly_returns,
    profit_factor,
    recovery_factor,
    sharpe_ratio,
    sortino_ratio,
    total_return,
    volatility,
    win_rate,
)
from src.strategy.reports import generate_html_report, generate_markdown_report
from src.strategy.equity_curve import plot_equity_curve, plot_drawdown


# ---------------------------------------------------------------------------
# Fixtures — synthetic data & a deterministic strategy
# ---------------------------------------------------------------------------

def _make_ohlcv(n: int = 500, start_price: float = 100.0, trend: float = 0.0003, seed: int = 42) -> pd.DataFrame:
    """Create synthetic daily OHLCV data with a slight upward drift."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range(start="2022-01-03", periods=n, freq="B")
    log_returns = rng.normal(trend, 0.02, n)
    close = start_price * np.exp(np.cumsum(log_returns))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    open_ = close * (1 + rng.normal(0, 0.005, n))
    volume = rng.randint(1_000_000, 10_000_000, n)
    df = pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, index=dates)
    return df


class AlwaysBuyStrategy(BaseStrategy):
    """Trivial strategy: always signals buy. Holds forever until backtest closes."""
    def __init__(self) -> None:
        config = Strategy(id="always_buy", name="Always Buy", min_confidence=0.0)
        super().__init__(config)

    def required_indicators(self): return []  # type: ignore[override]
    def minimum_data_points(self) -> int: return 2  # type: ignore[override]

    def evaluate(self, data: pd.DataFrame) -> "Signal":
        from src.strategy.signals import Signal
        return Signal(direction=1.0, confidence=1.0, strategy_id="always_buy")


class AlwaysSellStrategy(BaseStrategy):
    """Trivial strategy: always sell on first bar."""
    def __init__(self) -> None:
        config = Strategy(id="always_sell", name="Always Sell", min_confidence=0.0)
        super().__init__(config)

    def required_indicators(self): return []  # type: ignore[override]
    def minimum_data_points(self) -> int: return 2  # type: ignore[override]

    def evaluate(self, data: pd.DataFrame) -> "Signal":
        from src.strategy.signals import Signal
        if len(data) < 3:
            return Signal(direction=-1.0, confidence=1.0, strategy_id="always_sell")
        if len(data) == 2:
            return Signal(direction=-1.0, confidence=1.0, strategy_id="always_sell")
        return Signal(direction=0.0, confidence=0.0, strategy_id="always_sell")


class OscillatingStrategy(BaseStrategy):
    """Alternates buy/sell signals for multiple round-trip trades."""
    def __init__(self) -> None:
        config = Strategy(id="oscillating", name="Oscillating", min_confidence=0.0)
        super().__init__(config)

    def required_indicators(self): return []  # type: ignore[override]
    def minimum_data_points(self) -> int: return 2  # type: ignore[override]

    def evaluate(self, data: pd.DataFrame) -> "Signal":
        from src.strategy.signals import Signal
        n = len(data)
        if n < 3:
            return Signal(direction=1.0, confidence=1.0, strategy_id="oscillating")
        # Alternate buy/sell every 10 bars
        if (n // 10) % 2 == 0:
            return Signal(direction=1.0, confidence=1.0, strategy_id="oscillating")
        else:
            return Signal(direction=-1.0, confidence=1.0, strategy_id="oscillating")


@pytest.fixture
def ohlcv() -> pd.DataFrame:
    return _make_ohlcv(300, seed=99)


@pytest.fixture
def backtester() -> Backtester:
    return Backtester(initial_capital=100_000, position_size_pct=0.95)


# ---------------------------------------------------------------------------
# BacktestResult dataclass
# ---------------------------------------------------------------------------

class TestBacktestResult:
    def test_fields(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester()
        strat = OscillatingStrategy()
        result = bt.backtest(strat, ohlcv, symbol="TEST")
        assert isinstance(result, BacktestResult)
        assert result.strategy_id == "oscillating"
        assert result.symbol == "TEST"
        assert isinstance(result.period, str)
        assert isinstance(result.trade_log, list)
        assert len(result.equity_curve) > 0

    def test_summary_dict(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester()
        result = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        d = result.summary_dict()
        assert "sharpe_ratio" in d
        assert "max_drawdown" in d
        assert "win_rate" in d
        assert "total_trades" in d


# ---------------------------------------------------------------------------
# Backtester
# ---------------------------------------------------------------------------

class TestBacktester:
    def test_backtest_runs(self, ohlcv: pd.DataFrame, backtester: Backtester) -> None:
        result = backtester.backtest(OscillatingStrategy(), ohlcv, symbol="AAPL")
        assert result.total_trades >= 0
        assert isinstance(result.sharpe_ratio, float)
        assert result.max_drawdown <= 0

    def test_always_buy_produces_one_trade(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(initial_capital=100_000, signal_threshold=0.0)
        result = bt.backtest(AlwaysBuyStrategy(), ohlcv, symbol="X")
        # The always-buy buys early, then is neutral → 1 trade (closed at end)
        assert result.total_trades == 1

    def test_commission_reduces_return(self, ohlcv: pd.DataFrame) -> None:
        bt_no_comm = Backtester(initial_capital=100_000, commission=CommissionConfig(per_trade_fee=0.0))
        bt_high_comm = Backtester(
            initial_capital=100_000,
            commission=CommissionConfig(per_trade_fee=50.0),
        )
        strat = OscillatingStrategy()
        r1 = bt_no_comm.backtest(strat, ohlcv, symbol="T")
        r2 = bt_high_comm.backtest(strat, ohlcv, symbol="T")
        assert r2.total_return <= r1.total_return, "Higher fees should reduce return"

    def test_insufficient_data_returns_empty(self) -> None:
        """Use a strategy that needs >5 bars so 5-bar dataset is insufficient."""
        from src.strategy.signals import Signal as Sig

        class NeedMoreData(BaseStrategy):
            def __init__(self) -> None:
                cfg = Strategy(id="need_more", name="NeedMore", min_confidence=0.0)
                super().__init__(cfg)
            def required_indicators(self): return []  # type: ignore[override]
            def minimum_data_points(self) -> int: return 200  # type: ignore[override]
            def evaluate(self, data: pd.DataFrame) -> Sig:
                return Sig(direction=1.0, confidence=1.0, strategy_id="need_more")

        tiny = _make_ohlcv(5, seed=1)
        bt = Backtester()
        result = bt.backtest(NeedMoreData(), tiny, symbol="TINY")
        assert result.total_trades == 0
        assert result.total_return == 0.0

    def test_rank_strategies(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(signal_threshold=0.0)
        r1 = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        r2 = bt.backtest(AlwaysBuyStrategy(), ohlcv, symbol="T")
        ranked = Backtester.rank_strategies([r1, r2], metric="sharpe_ratio")
        assert len(ranked) == 2
        # Should be sorted descending by sharpe
        assert ranked[0].sharpe_ratio >= ranked[1].sharpe_ratio

    def test_compare_strategies(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(signal_threshold=0.0)
        r1 = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        r2 = bt.backtest(AlwaysBuyStrategy(), ohlcv, symbol="T")
        df = Backtester.compare_strategies([r1, r2])
        assert isinstance(df, pd.DataFrame)
        assert "sharpe_ratio" in df.columns
        assert len(df) == 2

    def test_walk_forward(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(signal_threshold=0.0)
        results = bt.walk_forward(
            OscillatingStrategy(), ohlcv, symbol="WF", n_splits=3, in_sample_pct=0.6,
        )
        assert isinstance(results, list)
        # At least 1 split should produce a valid result
        assert len(results) >= 1

    def test_backtest_all(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(signal_threshold=0.0)
        strategies = {
            "osc": OscillatingStrategy(),
            "buy": AlwaysBuyStrategy(),
        }
        results = bt.backtest_all(strategies, ohlcv, symbol="ALL")
        assert len(results) == 2


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics:
    def _equity(self, values: list[float]) -> pd.Series:
        idx = pd.bdate_range("2024-01-02", periods=len(values), freq="B")
        return pd.Series(values, index=idx)

    def test_total_return(self) -> None:
        eq = self._equity([100, 110, 121])
        assert abs(total_return(eq) - 0.21) < 1e-10

    def test_total_return_flat(self) -> None:
        eq = self._equity([100, 100, 100])
        assert total_return(eq) == 0.0

    def test_sharpe_positive_for_positive_drift(self) -> None:
        # Use strong drift and low risk-free rate to ensure positive Sharpe
        rng = np.random.RandomState(7)
        vals = np.cumsum(rng.normal(0.003, 0.01, 252)) + 100
        eq = self._equity(vals.tolist())
        assert sharpe_ratio(eq, risk_free_rate=0.0) > 0

    def test_max_drawdown(self) -> None:
        eq = self._equity([100, 120, 90, 110])
        mdd = max_drawdown(eq)
        # Peak=120, trough=90 → dd = (90-120)/120 = -0.25
        assert abs(mdd - (-0.25)) < 1e-10

    def test_win_rate(self) -> None:
        trades = [
            Trade(
                entry_date=datetime(2024, 1, 1), exit_date=datetime(2024, 1, 5),
                entry_price=100, exit_price=110, direction=1.0, shares=10,
                pnl=100, pnl_pct=0.10, holding_period_days=4, commission=0,
            ),
            Trade(
                entry_date=datetime(2024, 1, 10), exit_date=datetime(2024, 1, 15),
                entry_price=100, exit_price=90, direction=1.0, shares=10,
                pnl=-100, pnl_pct=-0.10, holding_period_days=5, commission=0,
            ),
        ]
        assert abs(win_rate(trades) - 0.5) < 1e-10

    def test_profit_factor(self) -> None:
        trades = [
            Trade(
                entry_date=datetime(2024, 1, 1), exit_date=datetime(2024, 1, 5),
                entry_price=100, exit_price=120, direction=1.0, shares=10,
                pnl=200, pnl_pct=0.20, holding_period_days=4, commission=0,
            ),
            Trade(
                entry_date=datetime(2024, 1, 10), exit_date=datetime(2024, 1, 15),
                entry_price=100, exit_price=95, direction=1.0, shares=10,
                pnl=-50, pnl_pct=-0.05, holding_period_days=5, commission=0,
            ),
        ]
        assert abs(profit_factor(trades) - 4.0) < 1e-10

    def test_sortino_ratio(self) -> None:
        eq = self._equity([100, 101, 103, 102, 105, 107, 106, 110])
        so = sortino_ratio(eq)
        assert isinstance(so, float)

    def test_volatility(self) -> None:
        eq = self._equity([100, 101, 100, 101, 100])
        vol = volatility(eq)
        assert vol >= 0

    def test_calmar_ratio(self) -> None:
        eq = self._equity([100, 120, 90, 130])
        cr = calmar_ratio(eq)
        assert isinstance(cr, float)

    def test_recovery_factor(self) -> None:
        eq = self._equity([100, 120, 90, 130])
        rf = recovery_factor(eq)
        assert isinstance(rf, float)

    def test_avg_win_loss(self) -> None:
        trades = [
            Trade(
                entry_date=datetime(2024, 1, 1), exit_date=datetime(2024, 1, 5),
                entry_price=100, exit_price=120, direction=1.0, shares=10,
                pnl=200, pnl_pct=0.20, holding_period_days=4, commission=0,
            ),
            Trade(
                entry_date=datetime(2024, 1, 10), exit_date=datetime(2024, 1, 15),
                entry_price=100, exit_price=95, direction=1.0, shares=10,
                pnl=-50, pnl_pct=-0.05, holding_period_days=5, commission=0,
            ),
        ]
        awl = avg_win_loss(trades)
        assert abs(awl["avg_win"] - 200) < 1e-10
        assert abs(awl["avg_loss"] - (-50)) < 1e-10

    def test_expectancy(self) -> None:
        trades = [
            Trade(
                entry_date=datetime(2024, 1, 1), exit_date=datetime(2024, 1, 5),
                entry_price=100, exit_price=120, direction=1.0, shares=10,
                pnl=200, pnl_pct=0.20, holding_period_days=4, commission=0,
            ),
            Trade(
                entry_date=datetime(2024, 1, 10), exit_date=datetime(2024, 1, 15),
                entry_price=100, exit_price=95, direction=1.0, shares=10,
                pnl=-50, pnl_pct=-0.05, holding_period_days=5, commission=0,
            ),
        ]
        assert abs(expectancy(trades) - 75.0) < 1e-10


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

class TestReports:
    def test_markdown_report(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(signal_threshold=0.0)
        r = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        md = generate_markdown_report([r])
        assert "# Backtesting Report" in md
        assert "oscillating" in md

    def test_html_report(self, ohlcv: pd.DataFrame) -> None:
        bt = Backtester(signal_threshold=0.0)
        r = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        html = generate_html_report([r])
        assert "<!DOCTYPE html>" in html
        assert "oscillating" in html


# ---------------------------------------------------------------------------
# Equity curve
# ---------------------------------------------------------------------------

class TestEquityCurve:
    def test_plot_equity_curve(self, ohlcv: pd.DataFrame, tmp_path: str) -> None:
        bt = Backtester(signal_threshold=0.0)
        r = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        out = str(tmp_path / "eq.png")
        path = plot_equity_curve(r, output_path=out)
        assert path == out
        import os
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0

    def test_plot_drawdown(self, ohlcv: pd.DataFrame, tmp_path: str) -> None:
        bt = Backtester(signal_threshold=0.0)
        r = bt.backtest(OscillatingStrategy(), ohlcv, symbol="T")
        out = str(tmp_path / "dd.png")
        path = plot_drawdown(r, output_path=out)
        assert path == out
        import os
        assert os.path.exists(path)
        assert os.path.getsize(path) > 0
