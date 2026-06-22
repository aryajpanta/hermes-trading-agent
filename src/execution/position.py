"""Position tracking for paper trading."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict


class Direction(str, Enum):
    """Trade direction."""

    LONG = "LONG"
    SHORT = "SHORT"


class PositionStatus(str, Enum):
    """Position lifecycle status."""

    OPEN = "OPEN"
    CLOSED = "CLOSED"


@dataclass
class Position:
    """Represents a single position in the paper trading portfolio.

    Attributes:
        symbol: Asset ticker symbol.
        direction: LONG or SHORT.
        entry_price: Price at which the position was opened.
        entry_time: Timestamp when the position was opened.
        quantity: Number of units held.
        stop_loss: Stop-loss price level.
        take_profit: Take-profit price level.
        strategy_id: Strategy that generated the signal.
        unrealized_pnl: Current unrealized P&L.
        status: OPEN or CLOSED.
        exit_price: Price at which the position was closed.
        exit_time: Timestamp when the position was closed.
        realized_pnl: P&L realized upon closing.
        close_reason: Why the position was closed (stop_loss, take_profit, signal).
    """

    symbol: str = ""
    direction: Direction = Direction.LONG
    entry_price: float = 0.0
    entry_time: datetime = field(default_factory=datetime.utcnow)
    quantity: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    strategy_id: str = ""
    unrealized_pnl: float = 0.0
    status: PositionStatus = PositionStatus.OPEN
    exit_price: float = 0.0
    exit_time: datetime = field(default_factory=datetime.utcnow)
    realized_pnl: float = 0.0
    close_reason: str = ""

    @property
    def market_value(self) -> float:
        """Market value of the position."""
        return self.quantity * self.entry_price

    def update_unrealized_pnl(self, current_price: float) -> float:
        """Update and return unrealized P&L based on current price."""
        if self.direction == Direction.LONG:
            self.unrealized_pnl = (current_price - self.entry_price) * self.quantity
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.quantity
        return self.unrealized_pnl

    def close(self, exit_price: float, reason: str = "") -> float:
        """Close the position and calculate realized P&L."""
        self.exit_price = exit_price
        self.exit_time = datetime.utcnow()
        self.status = PositionStatus.CLOSED
        self.close_reason = reason

        if self.direction == Direction.LONG:
            self.realized_pnl = (exit_price - self.entry_price) * self.quantity
        else:
            self.realized_pnl = (self.entry_price - exit_price) * self.quantity

        self.unrealized_pnl = 0.0
        return self.realized_pnl

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat(),
            "quantity": self.quantity,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "strategy_id": self.strategy_id,
            "unrealized_pnl": self.unrealized_pnl,
            "status": self.status.value,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time.isoformat(),
            "realized_pnl": self.realized_pnl,
            "close_reason": self.close_reason,
        }
