"""Order models and types for the broker integration.

Supports Market, Limit, Stop, and Stop-limit order types with
full lifecycle tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class OrderType(str, Enum):
    """Supported order types."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(str, Enum):
    """Order side (buy/sell)."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order lifecycle status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class ApprovalStatus(str, Enum):
    """Human approval gate status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    AUTO_APPROVED = "auto_approved"


@dataclass
class BrokerOrder:
    """Represents an order submitted to or tracked by the broker.

    Attributes:
        broker_id: Alpaca order ID (set after submission).
        symbol: Asset ticker.
        side: BUY or SELL.
        order_type: MARKET, LIMIT, STOP, or STOP_LIMIT.
        quantity: Number of shares/units.
        limit_price: Limit price (for limit / stop-limit orders).
        stop_price: Stop price (for stop / stop-limit orders).
        time_in_force: How long the order stays active.
        status: Current order status.
        filled_price: Average fill price.
        filled_quantity: How much was filled.
        submitted_at: When submitted to broker.
        filled_at: When fully filled.
        client_id: Our internal order identifier.
        approval_status: Human approval gate result.
        reasoning: Why this order was created.
        recommendation_id: Links back to TradeRecommendation.
    """

    symbol: str = ""
    side: OrderSide = OrderSide.BUY
    order_type: OrderType = OrderType.MARKET
    quantity: float = 0.0
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "day"
    status: OrderStatus = OrderStatus.PENDING
    filled_price: Optional[float] = None
    filled_quantity: float = 0.0
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    broker_id: Optional[str] = None
    client_id: str = ""
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    reasoning: str = ""
    recommendation_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "broker_id": self.broker_id,
            "client_id": self.client_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": self.quantity,
            "limit_price": self.limit_price,
            "stop_price": self.stop_price,
            "time_in_force": self.time_in_force,
            "status": self.status.value,
            "filled_price": self.filled_price,
            "filled_quantity": self.filled_quantity,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "approval_status": self.approval_status.value,
            "reasoning": self.reasoning,
            "recommendation_id": self.recommendation_id,
        }

    @classmethod
    def from_broker_response(cls, data: Dict[str, Any]) -> "BrokerOrder":
        """Create a BrokerOrder from an Alpaca API response dict."""
        from alpaca.trading.enums import OrderSide as AlpacaSide
        from alpaca.trading.enums import OrderStatus as AlpacaStatus
        from alpaca.trading.enums import OrderType as AlpacaType

        # Map Alpaca order type
        otype_map = {
            AlpacaType.MARKET: OrderType.MARKET,
            AlpacaType.LIMIT: OrderType.LIMIT,
            AlpacaType.STOP: OrderType.STOP,
            AlpacaType.STOP_LIMIT: OrderType.STOP_LIMIT,
        }
        side_map = {
            AlpacaSide.BUY: OrderSide.BUY,
            AlpacaSide.SELL: OrderSide.SELL,
        }
        status_map = {
            AlpacaStatus.NEW: OrderStatus.SUBMITTED,
            AlpacaStatus.PARTIALLY_FILLED: OrderStatus.PARTIALLY_FILLED,
            AlpacaStatus.FILLED: OrderStatus.FILLED,
            AlpacaStatus.CANCELED: OrderStatus.CANCELLED,
            AlpacaStatus.EXPIRED: OrderStatus.EXPIRED,
            AlpacaStatus.REJECTED: OrderStatus.REJECTED,
            AlpacaStatus.PENDING_NEW: OrderStatus.PENDING,
            AlpacaStatus.ACCEPTED: OrderStatus.SUBMITTED,
            AlpacaStatus.PENDING_CANCEL: OrderStatus.SUBMITTED,
        }

        raw_type = data.get("type", "market")
        raw_side = data.get("side", "buy")
        raw_status = data.get("status", "new")

        # Handle enum or string values
        def resolve_type(v: Any) -> OrderType:
            if isinstance(v, AlpacaType):
                return otype_map.get(v, OrderType.MARKET)
            return OrderType(str(v).lower())

        def resolve_side(v: Any) -> OrderSide:
            if isinstance(v, AlpacaSide):
                return side_map.get(v, OrderSide.BUY)
            return OrderSide(str(v).lower())

        def resolve_status(v: Any) -> OrderStatus:
            if isinstance(v, AlpacaStatus):
                return status_map.get(v, OrderStatus.SUBMITTED)
            return status_map.get(AlpacaStatus(str(v)), OrderStatus.SUBMITTED)

        limit_price = data.get("limit_price")
        stop_price = data.get("stop_price")
        filled_avg_price = data.get("filled_avg_price")

        return cls(
            broker_id=str(data.get("id", "")),
            client_id=str(data.get("client_order_id", "")),
            symbol=str(data.get("symbol", "")),
            side=resolve_side(raw_side),
            order_type=resolve_type(raw_type),
            quantity=float(data.get("qty", 0)),
            limit_price=float(limit_price) if limit_price else None,
            stop_price=float(stop_price) if stop_price else None,
            time_in_force=str(data.get("time_in_force", "day")),
            status=resolve_status(raw_status),
            filled_price=float(filled_avg_price) if filled_avg_price else None,
            filled_quantity=float(data.get("filled_qty", 0)),
            submitted_at=(
                datetime.fromisoformat(data["submitted_at"].replace("Z", "+00:00"))
                if data.get("submitted_at")
                else None
            ),
            filled_at=(
                datetime.fromisoformat(data["filled_at"].replace("Z", "+00:00"))
                if data.get("filled_at")
                else None
            ),
        )
