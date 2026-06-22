"""Paper trading engine — simulated trade execution with portfolio tracking.

Usage:
    python -m src.execution.paper --portfolio-status
    python -m src.execution.paper --execute '{"symbol":"AAPL","direction":"BUY",...}'
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List, Optional

# Ensure project root is on the path so `src.*` imports work when run as -m
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.execution.benchmark import BenchmarkComparison, compare_to_benchmarks
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


class PaperTrader:
    """Simulated trade execution engine.

    Manages a virtual portfolio, executes signals, manages positions,
    and tracks P&L with benchmark comparison.
    """

    def __init__(self, starting_capital: float = 100_000.0) -> None:
        self.portfolio = Portfolio(cash=starting_capital)
        self._trade_history: List[Dict[str, Any]] = []

    def execute_signal(self, signal: Dict[str, Any]) -> Optional[Position]:
        """Execute a trade signal to open or close a position.

        Args:
            signal: Dictionary with keys:
                symbol (str): Asset symbol.
                direction (str): "BUY" or "SELL".
                quantity (float): Number of units.
                price (float): Execution price.
                stop_loss (float, optional): Stop-loss level.
                take_profit (float, optional): Take-profit level.
                strategy_id (str, optional): Strategy identifier.
                confidence (float, optional): Signal confidence.

        Returns:
            New Position if opened, or None if signal was HOLD / invalid.
        """
        direction_str = signal.get("direction", "").upper()
        symbol = signal.get("symbol", "")
        quantity = float(signal.get("quantity", 0))
        price = float(signal.get("price", 0))

        if not symbol or quantity <= 0 or price <= 0:
            return None

        if direction_str == "BUY" or direction_str == "LONG":
            return self._open_position(
                symbol=symbol,
                direction=Direction.LONG,
                quantity=quantity,
                price=price,
                stop_loss=float(signal.get("stop_loss", 0)),
                take_profit=float(signal.get("take_profit", 0)),
                strategy_id=signal.get("strategy_id", ""),
            )
        elif direction_str == "SELL" or direction_str == "SHORT":
            # If we have an open LONG position, close it; otherwise open SHORT
            open_pos = self._find_open_position(symbol)
            if open_pos and open_pos.direction == Direction.LONG:
                return self._close_position(open_pos, price, reason="signal_sell")
            return self._open_position(
                symbol=symbol,
                direction=Direction.SHORT,
                quantity=quantity,
                price=price,
                stop_loss=float(signal.get("stop_loss", 0)),
                take_profit=float(signal.get("take_profit", 0)),
                strategy_id=signal.get("strategy_id", ""),
            )
        elif direction_str == "HOLD":
            return None
        else:
            return None

    def _open_position(
        self,
        symbol: str,
        direction: Direction,
        quantity: float,
        price: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
        strategy_id: str = "",
    ) -> Position:
        """Open a new position."""
        cost = price * quantity
        if cost > self.portfolio.cash:
            # Reduce quantity to what we can afford
            quantity = self.portfolio.cash / price if price > 0 else 0
            cost = price * quantity

        if quantity <= 0:
            raise ValueError("Insufficient cash to open position")

        self.portfolio.cash -= cost
        pos = Position(
            symbol=symbol,
            direction=direction,
            entry_price=price,
            entry_time=datetime.utcnow(),
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            strategy_id=strategy_id,
            status=PositionStatus.OPEN,
        )
        self.portfolio.positions.append(pos)
        return pos

    def _close_position(self, position: Position, exit_price: float, reason: str = "") -> Position:
        """Close an existing position."""
        position.close(exit_price, reason)
        # Return capital: initial cost + realized P&L
        self.portfolio.cash += position.quantity * position.entry_price + position.realized_pnl
        self._trade_history.append(position.to_dict())
        return position

    def _find_open_position(self, symbol: str) -> Optional[Position]:
        """Find the first open position for a symbol."""
        for p in self.portfolio.open_positions:
            if p.symbol == symbol:
                return p
        return None

    def update_positions(self, market_data: Dict[str, float]) -> None:
        """Update unrealized P&L for all open positions with current prices.

        Args:
            market_data: Dictionary mapping symbol -> current price.
        """
        for pos in self.portfolio.open_positions:
            price = market_data.get(pos.symbol)
            if price is not None:
                pos.update_unrealized_pnl(price)

        self.portfolio.update_value(market_data)

    def check_stops(self, market_data: Dict[str, float]) -> List[Position]:
        """Check and trigger stop-loss / take-profit for all open positions.

        Args:
            market_data: Dictionary mapping symbol -> current price.

        Returns:
            List of positions that were closed.
        """
        closed: List[Position] = []
        for pos in list(self.portfolio.open_positions):
            current_price = market_data.get(pos.symbol)
            if current_price is None:
                continue

            triggered = False
            reason = ""

            if pos.direction == Direction.LONG:
                if pos.stop_loss > 0 and current_price <= pos.stop_loss:
                    triggered = True
                    reason = "stop_loss"
                elif pos.take_profit > 0 and current_price >= pos.take_profit:
                    triggered = True
                    reason = "take_profit"
            else:  # SHORT
                if pos.stop_loss > 0 and current_price >= pos.stop_loss:
                    triggered = True
                    reason = "stop_loss"
                elif pos.take_profit > 0 and current_price <= pos.take_profit:
                    triggered = True
                    reason = "take_profit"

            if triggered:
                self._close_position(pos, current_price, reason)
                closed.append(pos)

        return closed

    def get_portfolio(self) -> Dict[str, Any]:
        """Get current portfolio state."""
        return {
            **self.portfolio.to_dict(),
            "positions": [p.to_dict() for p in self.portfolio.open_positions],
        }

    def get_history(self) -> List[Dict[str, Any]]:
        """Get all closed trades."""
        return [p.to_dict() for p in self.portfolio.closed_positions]

    def get_performance(self) -> Dict[str, Any]:
        """Get performance metrics."""
        return {
            "portfolio": self.portfolio.to_dict(),
            "trade_distribution": trade_distribution(self.portfolio.positions),
            "strategy_attribution": strategy_attribution(self.portfolio.positions),
        }

    def get_benchmark_comparison(
        self,
        sp500_prices: Optional[List[float]] = None,
        btc_prices: Optional[List[float]] = None,
        risk_free_rate: float = 0.04,
    ) -> Dict[str, Any]:
        """Compare portfolio to benchmarks.

        Args:
            sp500_prices: S&P 500 price series.
            btc_prices: BTC price series.
            risk_free_rate: Annual risk-free rate.

        Returns:
            Benchmark comparison dictionary.
        """
        comp = compare_to_benchmarks(
            self.portfolio.equity_curve,
            sp500_prices,
            btc_prices,
            risk_free_rate,
        )
        return comp.to_dict()

    def get_full_report(
        self,
        sp500_prices: Optional[List[float]] = None,
        btc_prices: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Generate full performance report with benchmarks."""
        benchmark = self.get_benchmark_comparison(sp500_prices, btc_prices)
        return full_report(self.portfolio.equity_curve, self.portfolio.positions, benchmark)

    def export_trades(self, fmt: str = "json", filepath: Optional[str] = None) -> str:
        """Export trade history to file.

        Args:
            fmt: "json" or "csv".
            filepath: Output file path. If None, uses default name.

        Returns:
            Path to the exported file.
        """
        trades = self.get_history()
        if not filepath:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filepath = f"trades_{timestamp}.{fmt}"

        if fmt == "csv":
            if not trades:
                # Create empty file
                with open(filepath, "w", newline="") as f:
                    f.write("")
            else:
                keys = list(trades[0].keys())
                with open(filepath, "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=keys)
                    writer.writeheader()
                    writer.writerows(trades)
        else:
            with open(filepath, "w") as f:
                json.dump(trades, f, indent=2, default=str)

        return filepath

    def get_daily_pnl(self, target_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Get daily P&L summary."""
        return daily_pnl_summary(self.portfolio.positions, target_date)

    def get_weekly_performance(self, week_start: Optional[datetime] = None) -> Dict[str, Any]:
        """Get weekly performance summary."""
        return weekly_performance(self.portfolio.positions, week_start)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Paper Trading Engine")
    parser.add_argument("--portfolio-status", action="store_true", help="Show portfolio status")
    parser.add_argument("--performance", action="store_true", help="Show performance metrics")
    parser.add_argument("--history", action="store_true", help="Show trade history")
    parser.add_argument("--execute", type=str, help="Execute a trade signal (JSON)")
    parser.add_argument("--export", type=str, nargs="?", const="json", help="Export trades")
    parser.add_argument("--capital", type=float, default=100_000.0, help="Starting capital")

    args = parser.parse_args()
    trader = PaperTrader(starting_capital=args.capital)

    if args.portfolio_status:
        status = trader.get_portfolio()
        print(json.dumps(status, indent=2, default=str))
    elif args.performance:
        perf = trader.get_performance()
        print(json.dumps(perf, indent=2, default=str))
    elif args.history:
        history = trader.get_history()
        print(json.dumps(history, indent=2, default=str))
    elif args.execute:
        signal = json.loads(args.execute)
        pos = trader.execute_signal(signal)
        if pos:
            print(json.dumps(pos.to_dict(), indent=2, default=str))
        else:
            print("No position opened (HOLD or invalid signal)")
    elif args.export:
        filepath = trader.export_trades(args.export)
        print(f"Exported to {filepath}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
