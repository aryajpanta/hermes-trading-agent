"""Portfolio management for paper trading."""

from dataclasses import dataclass, field
from typing import Any, Dict, List

import numpy as np

from src.execution.position import Position, PositionStatus


@dataclass
class Portfolio:
    """Paper trading portfolio state.

    Attributes:
        cash: Available cash balance.
        positions: List of all positions (open and closed).
        total_value: Total portfolio value (cash + position values).
        daily_pnl: Today's P&L.
        total_pnl: Cumulative P&L.
        win_rate: Fraction of closed trades that were profitable.
        sharpe_ratio: Annualized Sharpe ratio of the equity curve.
    """

    cash: float = 100_000.0
    positions: List[Position] = field(default_factory=list)
    total_value: float = 100_000.0
    daily_pnl: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    _starting_capital: float = 100_000.0
    _equity_curve: List[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._starting_capital = self.cash
        self.total_value = self.cash
        if not self._equity_curve:
            self._equity_curve = [self.cash]

    @property
    def open_positions(self) -> List[Position]:
        """Positions that are currently open."""
        return [p for p in self.positions if p.status == PositionStatus.OPEN]

    @property
    def closed_positions(self) -> List[Position]:
        """Positions that have been closed."""
        return [p for p in self.positions if p.status == PositionStatus.CLOSED]

    def position_value(self, current_prices: Dict[str, float]) -> float:
        """Total market value of open positions at given prices."""
        value = 0.0
        for pos in self.open_positions:
            price = current_prices.get(pos.symbol, pos.entry_price)
            if pos.direction.value == "LONG":
                value += price * pos.quantity
            else:
                value += (2 * pos.entry_price - price) * pos.quantity
        return value

    def update_value(self, current_prices: Dict[str, float]) -> float:
        """Recalculate total portfolio value and equity curve."""
        pos_val = self.position_value(current_prices)
        self.total_value = self.cash + pos_val
        self._equity_curve.append(self.total_value)
        self.total_pnl = self.total_value - self._starting_capital
        self._update_win_rate()
        self._update_sharpe()
        return self.total_value

    def _update_win_rate(self) -> None:
        """Recalculate win rate from closed positions."""
        closed = self.closed_positions
        if not closed:
            self.win_rate = 0.0
            return
        wins = sum(1 for p in closed if p.realized_pnl > 0)
        self.win_rate = wins / len(closed)

    def _update_sharpe(self) -> None:
        """Recalculate Sharpe ratio from equity curve."""
        if len(self._equity_curve) < 3:
            self.sharpe_ratio = 0.0
            return
        arr = np.array(self._equity_curve, dtype=float)
        returns = np.diff(arr) / arr[:-1]
        returns = returns[~np.isnan(returns)]
        if len(returns) < 2 or np.std(returns) == 0:
            self.sharpe_ratio = 0.0
            return
        risk_free_daily = 0.04 / 252
        excess = returns.mean() - risk_free_daily
        self.sharpe_ratio = float(excess / np.std(returns, ddof=1) * np.sqrt(252))

    @property
    def equity_curve(self) -> List[float]:
        """Copy of the equity curve."""
        return list(self._equity_curve)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the portfolio to a dictionary."""
        return {
            "cash": self.cash,
            "total_value": self.total_value,
            "daily_pnl": self.daily_pnl,
            "total_pnl": self.total_pnl,
            "win_rate": self.win_rate,
            "sharpe_ratio": self.sharpe_ratio,
            "open_positions": len(self.open_positions),
            "closed_positions": len(self.closed_positions),
            "equity_curve_length": len(self._equity_curve),
        }
