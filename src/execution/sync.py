"""Portfolio synchronization between local state and broker.

Keeps the local portfolio model in sync with what the broker reports,
detecting discrepancies and logging sync events.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class BrokerPosition:
    """A position as reported by the broker.

    Attributes:
        symbol: Ticker symbol.
        quantity: Number of shares/units.
        avg_entry_price: Average entry price.
        current_price: Current market price.
        unrealized_pnl: Unrealized profit/loss.
        unrealized_pnl_pct: Unrealized P&L as percentage.
        market_value: Total market value of position.
        side: long or short.
    """

    symbol: str = ""
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    market_value: float = 0.0
    side: str = "long"

    @classmethod
    def from_broker(cls, data: Dict[str, Any]) -> "BrokerPosition":
        """Create from Alpaca position response."""
        qty = float(data.get("qty", 0))
        return cls(
            symbol=str(data.get("symbol", "")),
            quantity=qty,
            avg_entry_price=float(data.get("avg_entry_price", 0)),
            current_price=float(data.get("current_price", 0)),
            unrealized_pnl=float(data.get("unrealized_pl", 0)),
            unrealized_pnl_pct=float(data.get("unrealized_plpc", 0)),
            market_value=float(data.get("market_value", 0)),
            side=str(data.get("side", "long")),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_entry_price": self.avg_entry_price,
            "current_price": self.current_price,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "market_value": self.market_value,
            "side": self.side,
        }


@dataclass
class SyncResult:
    """Result of a portfolio sync operation.

    Attributes:
        broker_positions: Positions from broker.
        local_symbols: Symbols we expected to hold.
        broker_symbols: Symbols broker says we hold.
        added: Positions added locally to match broker.
        removed: Positions removed locally (not at broker).
        unchanged: Positions that matched.
        synced_at: When sync completed.
        errors: Any errors during sync.
    """

    broker_positions: List[BrokerPosition] = field(default_factory=list)
    local_symbols: List[str] = field(default_factory=list)
    broker_symbols: List[str] = field(default_factory=list)
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    unchanged: List[str] = field(default_factory=list)
    synced_at: Optional[datetime] = None
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "broker_positions": [p.to_dict() for p in self.broker_positions],
            "local_symbols": self.local_symbols,
            "broker_symbols": self.broker_symbols,
            "added": self.added,
            "removed": self.removed,
            "unchanged": self.unchanged,
            "synced_at": self.synced_at.isoformat() if self.synced_at else None,
            "errors": self.errors,
        }


class PortfolioSync:
    """Synchronizes local portfolio state with broker-reported positions.

    Detects discrepancies between what we think we hold and what the
    broker says, then reconciles.
    """

    def __init__(self) -> None:
        self._last_sync: Optional[SyncResult] = None

    @property
    def last_sync(self) -> Optional[SyncResult]:
        """Most recent sync result."""
        return self._last_sync

    def sync(
        self,
        broker_positions: List[Dict[str, Any]],
        local_positions: List[Dict[str, Any]],
    ) -> SyncResult:
        """Compare broker positions with local positions and reconcile.

        Args:
            broker_positions: Raw position dicts from broker API.
            local_positions: Local position dicts with at least 'symbol' key.

        Returns:
            SyncResult with discrepancy details.
        """
        result = SyncResult(synced_at=datetime.utcnow())

        # Parse broker positions
        broker_map: Dict[str, BrokerPosition] = {}
        for raw in broker_positions:
            bp = BrokerPosition.from_broker(raw)
            broker_map[bp.symbol] = bp
            result.broker_positions.append(bp)

        result.broker_symbols = sorted(broker_map.keys())

        # Parse local symbols
        local_symbols = {p.get("symbol", "") for p in local_positions if p.get("symbol")}
        result.local_symbols = sorted(local_symbols)

        # Find discrepancies
        all_symbols = local_symbols | set(broker_map.keys())

        for symbol in sorted(all_symbols):
            in_local = symbol in local_symbols
            in_broker = symbol in broker_map

            if in_local and in_broker:
                result.unchanged.append(symbol)
            elif in_broker and not in_local:
                result.added.append(symbol)
                logger.warning(
                    "Position %s exists at broker but not locally — "
                    "added to sync",
                    symbol,
                )
            elif in_local and not in_broker:
                result.removed.append(symbol)
                logger.warning(
                    "Position %s exists locally but not at broker — "
                    "removed from sync",
                    symbol,
                )

        logger.info(
            "Portfolio sync: %d broker, %d local, %d added, %d removed, %d unchanged",
            len(result.broker_symbols),
            len(result.local_symbols),
            len(result.added),
            len(result.removed),
            len(result.unchanged),
        )

        self._last_sync = result
        return result

    def get_broker_positions_dicts(self) -> List[Dict[str, Any]]:
        """Get last synced broker positions as plain dicts."""
        if not self._last_sync:
            return []
        return [p.to_dict() for p in self._last_sync.broker_positions]

    def get_total_unrealized_pnl(self) -> float:
        """Sum unrealized P&L across all broker positions."""
        if not self._last_sync:
            return 0.0
        return sum(p.unrealized_pnl for p in self._last_sync.broker_positions)
