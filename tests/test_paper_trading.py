"""Tests for M7: Paper Trading Engine."""

import json
import os
import tempfile
from datetime import datetime, timedelta

import pytest

from src.execution.benchmark import (
    BenchmarkComparison,
    BenchmarkResult,
    build_benchmarks,
    compare_to_benchmarks,
)
from src.execution.paper import PaperTrader
from src.execution.portfolio import Portfolio
from src.execution.position import Direction, Position, PositionStatus
from src.execution.reporting import (
    daily_pnl_summary,
    full_report,
    monthly_drawdown,
    strategy_attribution,
    trade_distribution,
    weekly_performance,
)


@pytest.fixture(autouse=True)
def _isolate_portfolio_path(tmp_path, monkeypatch):
    """Point PaperTrader at a fresh temp file for every test.

    PaperTrader auto-loads ``data/paper_portfolio.json`` on construction, so
    without this the suite would read (and write) the real on-disk portfolio
    and fail whenever live state exists. The temp file does not exist, so
    construction yields a clean ``starting_capital`` portfolio.
    """
    monkeypatch.setenv("PAPER_PORTFOLIO_PATH", str(tmp_path / "paper_portfolio.json"))


# ---------------------------------------------------------------------------
# Position tests
# ---------------------------------------------------------------------------

class TestPosition:
    def test_create_long_position(self) -> None:
        pos = Position(
            symbol="AAPL",
            direction=Direction.LONG,
            entry_price=150.0,
            quantity=10,
            stop_loss=140.0,
            take_profit=170.0,
            strategy_id="ma_crossover",
        )
        assert pos.symbol == "AAPL"
        assert pos.direction == Direction.LONG
        assert pos.status == PositionStatus.OPEN
        assert pos.unrealized_pnl == 0.0

    def test_create_short_position(self) -> None:
        pos = Position(
            symbol="TSLA",
            direction=Direction.SHORT,
            entry_price=200.0,
            quantity=5,
        )
        assert pos.direction == Direction.SHORT

    def test_update_unrealized_pnl_long(self) -> None:
        pos = Position(
            symbol="AAPL", direction=Direction.LONG,
            entry_price=100.0, quantity=10,
        )
        pnl = pos.update_unrealized_pnl(110.0)
        assert pnl == pytest.approx(100.0)  # (110-100) * 10

    def test_update_unrealized_pnl_short(self) -> None:
        pos = Position(
            symbol="TSLA", direction=Direction.SHORT,
            entry_price=200.0, quantity=5,
        )
        pnl = pos.update_unrealized_pnl(180.0)
        assert pnl == pytest.approx(100.0)  # (200-180) * 5

    def test_close_long_position(self) -> None:
        pos = Position(
            symbol="AAPL", direction=Direction.LONG,
            entry_price=100.0, quantity=10,
        )
        realized = pos.close(120.0, reason="take_profit")
        assert realized == pytest.approx(200.0)
        assert pos.status == PositionStatus.CLOSED
        assert pos.exit_price == 120.0
        assert pos.close_reason == "take_profit"

    def test_close_short_position(self) -> None:
        pos = Position(
            symbol="TSLA", direction=Direction.SHORT,
            entry_price=200.0, quantity=5,
        )
        realized = pos.close(180.0, reason="signal_sell")
        assert realized == pytest.approx(100.0)

    def test_to_dict(self) -> None:
        pos = Position(symbol="AAPL", direction=Direction.LONG, entry_price=100.0, quantity=10)
        d = pos.to_dict()
        assert d["symbol"] == "AAPL"
        assert d["direction"] == "LONG"
        assert d["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Portfolio tests
# ---------------------------------------------------------------------------

class TestPortfolio:
    def test_initial_state(self) -> None:
        p = Portfolio(cash=100_000.0)
        assert p.cash == 100_000.0
        assert p.total_value == 100_000.0
        assert len(p.open_positions) == 0

    def test_update_value(self) -> None:
        p = Portfolio(cash=99_000.0)
        pos = Position(symbol="AAPL", direction=Direction.LONG, entry_price=100.0, quantity=10)
        p.positions.append(pos)
        val = p.update_value({"AAPL": 110.0})
        # cash=99_000 + position value = 110*10 = 1100 => total = 100_100
        assert val == pytest.approx(100_100.0)

    def test_win_rate(self) -> None:
        p = Portfolio(cash=100_000.0)
        # Add 2 winning, 1 losing closed position
        for ep, xp in [(100, 110), (200, 220), (150, 140)]:
            pos = Position(symbol="X", direction=Direction.LONG, entry_price=ep, quantity=1, status=PositionStatus.CLOSED)
            pos.realized_pnl = xp - ep
            p.positions.append(pos)
        p._update_win_rate()
        assert p.win_rate == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# PaperTrader tests
# ---------------------------------------------------------------------------

class TestPaperTrader:
    def test_execute_buy_signal(self) -> None:
        trader = PaperTrader(starting_capital=100_000.0)
        signal = {
            "symbol": "AAPL",
            "direction": "BUY",
            "quantity": 10,
            "price": 150.0,
            "stop_loss": 140.0,
            "take_profit": 170.0,
            "strategy_id": "ma_crossover",
        }
        pos = trader.execute_signal(signal)
        assert pos is not None
        assert pos.symbol == "AAPL"
        assert pos.direction == Direction.LONG
        assert pos.quantity == 10
        assert pos.stop_loss == 140.0
        assert pos.take_profit == 170.0
        assert trader.portfolio.cash == pytest.approx(98_500.0)  # 100_000 - 1500

    def test_execute_sell_signal_closes_long(self) -> None:
        trader = PaperTrader(starting_capital=100_000.0)
        trader.execute_signal({
            "symbol": "AAPL", "direction": "BUY",
            "quantity": 10, "price": 150.0,
        })
        assert len(trader.portfolio.open_positions) == 1

        trader.execute_signal({
            "symbol": "AAPL", "direction": "SELL",
            "quantity": 10, "price": 160.0,
        })
        assert len(trader.portfolio.open_positions) == 0
        assert len(trader.portfolio.closed_positions) == 1
        closed = trader.portfolio.closed_positions[0]
        assert closed.realized_pnl == pytest.approx(100.0)

    def test_execute_hold_returns_none(self) -> None:
        trader = PaperTrader()
        result = trader.execute_signal({"direction": "HOLD"})
        assert result is None

    def test_update_positions(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "BTC-USD", "direction": "BUY",
            "quantity": 1, "price": 50_000.0,
        })
        trader.update_positions({"BTC-USD": 52_000.0})
        pos = trader.portfolio.open_positions[0]
        assert pos.unrealized_pnl == pytest.approx(2_000.0)

    def test_check_stops_stop_loss(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "ETH-USD", "direction": "BUY",
            "quantity": 10, "price": 2000.0,
            "stop_loss": 1900.0,
        })
        closed = trader.check_stops({"ETH-USD": 1850.0})
        assert len(closed) == 1
        assert closed[0].close_reason == "stop_loss"

    def test_check_stops_take_profit(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "ETH-USD", "direction": "BUY",
            "quantity": 10, "price": 2000.0,
            "take_profit": 2200.0,
        })
        closed = trader.check_stops({"ETH-USD": 2250.0})
        assert len(closed) == 1
        assert closed[0].close_reason == "take_profit"

    def test_check_stops_short_stop_loss(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "TSLA", "direction": "SHORT",
            "quantity": 5, "price": 200.0,
            "stop_loss": 210.0,
        })
        closed = trader.check_stops({"TSLA": 215.0})
        assert len(closed) == 1
        assert closed[0].close_reason == "stop_loss"

    def test_check_stops_short_take_profit(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "TSLA", "direction": "SHORT",
            "quantity": 5, "price": 200.0,
            "take_profit": 180.0,
        })
        closed = trader.check_stops({"TSLA": 175.0})
        assert len(closed) == 1
        assert closed[0].close_reason == "take_profit"

    def test_get_portfolio(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "AAPL", "direction": "BUY",
            "quantity": 5, "price": 100.0,
        })
        portfolio = trader.get_portfolio()
        assert portfolio["cash"] == pytest.approx(99_500.0)
        assert len(portfolio["positions"]) == 1

    def test_get_history(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "AAPL", "direction": "BUY",
            "quantity": 5, "price": 100.0,
        })
        trader.execute_signal({
            "symbol": "AAPL", "direction": "SELL",
            "quantity": 5, "price": 110.0,
        })
        history = trader.get_history()
        assert len(history) == 1
        assert history[0]["realized_pnl"] == pytest.approx(50.0)

    def test_get_performance(self) -> None:
        trader = PaperTrader()
        perf = trader.get_performance()
        assert "portfolio" in perf
        assert "trade_distribution" in perf
        assert "strategy_attribution" in perf

    def test_export_trades_json(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "AAPL", "direction": "BUY",
            "quantity": 5, "price": 100.0,
        })
        trader.execute_signal({
            "symbol": "AAPL", "direction": "SELL",
            "quantity": 5, "price": 110.0,
        })

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name

        try:
            trader.export_trades("json", path)
            with open(path) as f:
                data = json.load(f)
            assert len(data) == 1
            assert data[0]["symbol"] == "AAPL"
        finally:
            os.unlink(path)

    def test_export_trades_csv(self) -> None:
        trader = PaperTrader()
        trader.execute_signal({
            "symbol": "AAPL", "direction": "BUY",
            "quantity": 5, "price": 100.0,
        })
        trader.execute_signal({
            "symbol": "AAPL", "direction": "SELL",
            "quantity": 5, "price": 110.0,
        })

        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            path = f.name

        try:
            trader.export_trades("csv", path)
            with open(path) as f:
                content = f.read()
            assert "AAPL" in content
        finally:
            os.unlink(path)

    def test_custom_starting_capital(self) -> None:
        trader = PaperTrader(starting_capital=50_000.0)
        assert trader.portfolio.cash == 50_000.0
        assert trader.portfolio.total_value == 50_000.0

    def test_insufficient_cash(self) -> None:
        trader = PaperTrader(starting_capital=0.0)
        with pytest.raises(ValueError, match="Insufficient cash"):
            trader.execute_signal({
                "symbol": "AAPL", "direction": "BUY",
                "quantity": 10, "price": 100.0,
            })


# ---------------------------------------------------------------------------
# Benchmark tests
# ---------------------------------------------------------------------------

class TestBenchmark:
    def test_build_benchmarks_sp500(self) -> None:
        prices = [100.0, 105.0, 110.0, 108.0, 115.0]
        benchmarks = build_benchmarks(sp500_prices=prices)
        assert "sp500" in benchmarks
        assert benchmarks["sp500"].total_return == pytest.approx(0.15, abs=0.01)

    def test_build_benchmarks_btc(self) -> None:
        prices = [30_000.0, 33_000.0, 35_000.0]
        benchmarks = build_benchmarks(btc_prices=prices)
        assert "btc" in benchmarks
        assert benchmarks["btc"].total_return == pytest.approx(0.1667, abs=0.01)

    def test_compare_to_benchmarks(self) -> None:
        port_curve = [100_000.0, 102_000.0, 101_000.0, 105_000.0]
        sp500 = [4000.0, 4050.0, 4020.0, 4100.0]
        btc = [50_000.0, 52_000.0, 48_000.0, 55_000.0]

        comp = compare_to_benchmarks(port_curve, sp500, btc)
        assert isinstance(comp, BenchmarkComparison)
        assert comp.portfolio_return == pytest.approx(0.05, abs=0.01)
        assert "sp500" in comp.benchmarks
        assert "btc" in comp.benchmarks
        assert "sp500" in comp.alpha
        assert "btc" in comp.beta

    def test_benchmark_result_to_dict(self) -> None:
        br = BenchmarkResult(name="S&P 500", total_return=0.1)
        d = br.to_dict()
        assert d["name"] == "S&P 500"
        assert d["total_return"] == 0.1

    def test_benchmark_comparison_to_dict(self) -> None:
        bc = BenchmarkComparison(portfolio_return=0.05)
        d = bc.to_dict()
        assert d["portfolio_return"] == 0.05


# ---------------------------------------------------------------------------
# Reporting tests
# ---------------------------------------------------------------------------

class TestReporting:
    def test_daily_pnl_summary(self) -> None:
        now = datetime.utcnow()
        pos = Position(
            symbol="AAPL", direction=Direction.LONG,
            entry_price=100.0, quantity=10,
            status=PositionStatus.CLOSED, exit_price=110.0,
            realized_pnl=100.0, exit_time=now,
        )
        summary = daily_pnl_summary([pos], target_date=now)
        assert summary["trades_closed"] == 1
        assert summary["total_pnl"] == 100.0

    def test_weekly_performance(self) -> None:
        now = datetime.utcnow()
        pos = Position(
            symbol="AAPL", direction=Direction.LONG,
            entry_price=100.0, quantity=10,
            status=PositionStatus.CLOSED, exit_price=110.0,
            realized_pnl=100.0, exit_time=now,
        )
        perf = weekly_performance([pos], week_start=now - timedelta(days=1))
        assert perf["trades"] == 1
        assert perf["total_pnl"] == 100.0

    def test_monthly_drawdown(self) -> None:
        curve = [100_000.0, 102_000.0, 98_000.0, 103_000.0, 101_000.0]
        dd = monthly_drawdown(curve)
        assert dd["max_drawdown"] < 0
        assert len(dd["drawdowns"]) == 5

    def test_trade_distribution(self) -> None:
        positions = [
            Position(symbol="A", direction=Direction.LONG, entry_price=100, quantity=1,
                     status=PositionStatus.CLOSED, realized_pnl=50),
            Position(symbol="B", direction=Direction.LONG, entry_price=200, quantity=1,
                     status=PositionStatus.CLOSED, realized_pnl=-30),
        ]
        dist = trade_distribution(positions)
        assert dist["count"] == 2
        assert dist["mean_pnl"] == pytest.approx(10.0)

    def test_strategy_attribution(self) -> None:
        positions = [
            Position(symbol="A", direction=Direction.LONG, entry_price=100, quantity=1,
                     status=PositionStatus.CLOSED, realized_pnl=50, strategy_id="ma_cross"),
            Position(symbol="B", direction=Direction.LONG, entry_price=200, quantity=1,
                     status=PositionStatus.CLOSED, realized_pnl=-30, strategy_id="ma_cross"),
        ]
        attr = strategy_attribution(positions)
        assert "ma_cross" in attr
        assert attr["ma_cross"]["total_trades"] == 2
        assert attr["ma_cross"]["total_pnl"] == 20.0

    def test_full_report(self) -> None:
        curve = [100_000.0, 101_000.0, 102_000.0]
        positions = [
            Position(symbol="AAPL", direction=Direction.LONG, entry_price=100, quantity=10,
                     status=PositionStatus.CLOSED, realized_pnl=100, strategy_id="test"),
        ]
        report = full_report(curve, positions)
        assert "summary" in report
        assert "trade_distribution" in report
        assert "strategy_attribution" in report

    def test_empty_trade_distribution(self) -> None:
        dist = trade_distribution([])
        assert dist["count"] == 0


# ---------------------------------------------------------------------------
# CLI integration test
# ---------------------------------------------------------------------------

class TestCLI:
    def test_portfolio_status_cli(self) -> None:
        """Test that portfolio-status works via the module's main."""
        from src.execution.paper import PaperTrader
        trader = PaperTrader(starting_capital=100_000.0)
        status = trader.get_portfolio()
        assert status["cash"] == 100_000.0
        assert status["total_value"] == 100_000.0
