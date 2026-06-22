"""Broker integration with Alpaca Markets API.

Provides:
- Paper and live trading via Alpaca REST API
- Human approval gates for live trades
- Safety gates: mode, require_approval, max_daily_trades, max_daily_loss_pct
- Emergency controls: stop, pause, resume, circuit breaker
- CLI interface for account status and operations

Usage:
    python -m src.execution.broker --account-status
    python -m src.execution.broker --positions
    python -m src.execution.broker --orders
"""

import argparse
import json
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import yaml

# Ensure project root is on path for -m execution
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.execution.orders import (
    ApprovalStatus,
    BrokerOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.execution.emergency import EmergencyController
from src.execution.sync import PortfolioSync

logger = logging.getLogger(__name__)


class TradingMode(str, Enum):
    """Trading mode: paper or live."""

    PAPER = "PAPER"
    LIVE = "LIVE"


@dataclass
class ExecutionConfig:
    """Safety gate configuration for order execution.

    Attributes:
        mode: PAPER or LIVE.
        require_approval: Whether human approval is required per trade.
        max_daily_trades: Maximum number of trades per day.
        max_daily_loss_pct: Auto-pause when daily loss exceeds this fraction.
        emergency_stop: Kill switch flag.
    """

    mode: TradingMode = TradingMode.PAPER
    require_approval: bool = True
    max_daily_trades: int = 10
    max_daily_loss_pct: float = 0.02
    emergency_stop: bool = False

    @classmethod
    def from_yaml(cls, path: str) -> "ExecutionConfig":
        """Load config from broker_config.yaml."""
        with open(path) as f:
            raw = yaml.safe_load(f)
        exec_raw = raw.get("execution", {})
        mode_str = exec_raw.get("mode", "PAPER")
        return cls(
            mode=TradingMode(mode_str.upper()) if mode_str.upper() in ("PAPER", "LIVE") else TradingMode.PAPER,
            require_approval=exec_raw.get("require_approval", True),
            max_daily_trades=exec_raw.get("max_daily_trades", 10),
            max_daily_loss_pct=exec_raw.get("max_daily_loss_pct", 0.02),
            emergency_stop=exec_raw.get("emergency_stop", False),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "mode": self.mode.value,
            "require_approval": self.require_approval,
            "max_daily_trades": self.max_daily_trades,
            "max_daily_loss_pct": self.max_daily_loss_pct,
            "emergency_stop": self.emergency_stop,
        }


class AlpacaBroker:
    """Alpaca Markets broker integration.

    Provides order management, account queries, portfolio sync, and
    safety controls for both paper and live trading.

    Args:
        api_key: Alpaca API key. Falls back to ALPACA_API_KEY env var.
        secret_key: Alpaca secret key. Falls back to ALPACA_SECRET_KEY env var.
        config: Execution configuration. Loaded from YAML if None.
        base_url: Override base URL (for testing).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        config: Optional[ExecutionConfig] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        self._base_url = base_url
        self._client: Any = None  # TradingClient, set on connect()
        self._connected = False

        # Config
        if config is not None:
            self._config = config
        else:
            config_path = os.path.join(_project_root, "configs", "broker_config.yaml")
            if os.path.exists(config_path):
                self._config = ExecutionConfig.from_yaml(config_path)
            else:
                self._config = ExecutionConfig()

        # Safety state
        self._daily_trade_count = 0
        self._daily_trades_date: Optional[date] = None
        self._daily_pnl: float = 0.0

        # Emergency controller
        self._emergency = EmergencyController()
        self._emergency.set_emergency_stop_callback(self._handle_emergency_stop)

        # Portfolio sync
        self._sync = PortfolioSync()

        # Order history
        self._order_history: List[BrokerOrder] = []
        self._pending_approvals: List[BrokerOrder] = []

    @property
    def config(self) -> ExecutionConfig:
        """Current execution configuration."""
        return self._config

    @property
    def emergency(self) -> EmergencyController:
        """Emergency controller."""
        return self._emergency

    @property
    def connected(self) -> bool:
        """Whether connected to broker."""
        return self._connected

    # ---- Connection ----

    def connect(self, api_key: Optional[str] = None, secret_key: Optional[str] = None) -> Dict[str, Any]:
        """Connect to the Alpaca API.

        Args:
            api_key: Override API key.
            secret_key: Override secret key.

        Returns:
            Connection status dictionary.
        """
        key = api_key or self._api_key
        secret = secret_key or self._secret_key

        if not key or not secret:
            return {
                "connected": False,
                "error": "Missing API key or secret key. "
                "Pass directly or set ALPACA_API_KEY / ALPACA_SECRET_KEY env vars.",
            }

        try:
            from alpaca.trading.client import TradingClient

            kwargs: Dict[str, Any] = {"api_key": key, "secret_key": secret}
            if self._config.mode == TradingMode.PAPER:
                kwargs["paper"] = True
            if self._base_url:
                kwargs["url_override"] = self._base_url

            self._client = TradingClient(**kwargs)
            self._api_key = key
            self._secret_key = secret
            self._connected = True

            logger.info("Connected to Alpaca (%s mode)", self._config.mode.value)
            return {"connected": True, "mode": self._config.mode.value}
        except Exception as exc:
            logger.error("Connection failed: %s", exc)
            return {"connected": False, "error": str(exc)}

    # ---- Safety Gates ----

    def _check_safety_gates(self) -> Optional[str]:
        """Run all safety checks before order submission.

        Returns:
            Error message if a gate blocks the trade, or None if OK.
        """
        # Emergency stop
        if self._config.emergency_stop or self._emergency.state.emergency_stop:
            return "Emergency stop is active — trading halted"

        # Emergency controller
        if not self._emergency.is_trading_allowed():
            return f"Trading is paused: {self._emergency.state.pause_reason}"

        # Daily trade count
        today = date.today()
        if self._daily_trades_date != today:
            self._daily_trade_count = 0
            self._daily_pnl = 0.0
            self._daily_trades_date = today

        if self._daily_trade_count >= self._config.max_daily_trades:
            return (
                f"Daily trade limit reached: {self._daily_trade_count}/"
                f"{self._config.max_daily_trades}"
            )

        # Daily loss limit
        if self._config.max_daily_loss_pct > 0:
            try:
                acct = self.get_account()
                equity = float(acct.get("equity", 0))
                if equity > 0 and abs(self._daily_pnl / equity) > self._config.max_daily_loss_pct:
                    return (
                        f"Daily loss limit exceeded: {self._daily_pnl:.2f} "
                        f"({abs(self._daily_pnl / equity) * 100:.2f}%)"
                    )
            except Exception:
                pass  # If we can't check, allow the trade

        return None

    def _handle_emergency_stop(self) -> None:
        """Callback for emergency stop — cancel all orders."""
        try:
            self.cancel_all_orders()
        except Exception as exc:
            logger.error("Failed to cancel orders during emergency stop: %s", exc)

    # ---- Order Management ----

    def submit_order(
        self,
        recommendation: Any,
        order_type: OrderType = OrderType.LIMIT,
        limit_price: Optional[float] = None,
        stop_price: Optional[float] = None,
        time_in_force: str = "day",
        auto_approve: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Submit an order based on a TradeRecommendation or dict.

        Args:
            recommendation: TradeRecommendation object or dict with keys:
                symbol, direction, entry_price, stop_loss, quantity, etc.
            order_type: Type of order to place.
            limit_price: Override limit price.
            stop_price: Override stop price.
            time_in_force: Order time-in-force.
            auto_approve: Override approval behavior.

        Returns:
            Order result dictionary.
        """
        # Safety gates
        block_reason = self._check_safety_gates()
        if block_reason:
            return {"success": False, "error": block_reason}

        # Extract order details from recommendation
        if hasattr(recommendation, "to_dict"):
            rec_dict = recommendation.to_dict()
        elif isinstance(recommendation, dict):
            rec_dict = recommendation
        else:
            return {"success": False, "error": "Invalid recommendation type"}

        symbol = rec_dict.get("symbol", "")
        direction = str(rec_dict.get("direction", "BUY")).upper()

        if not symbol:
            return {"success": False, "error": "Missing symbol"}

        # Determine side
        if direction in ("BUY", "LONG"):
            side = OrderSide.BUY
        elif direction in ("SELL", "SHORT"):
            side = OrderSide.SELL
        else:
            return {"success": False, "error": f"Unknown direction: {direction}"}

        # Quantity from recommendation or calculate from position_size_pct
        quantity = float(rec_dict.get("quantity", 0))
        if quantity <= 0:
            position_size_pct = float(rec_dict.get("position_size_pct", 0.05))
            entry_price = float(rec_dict.get("entry_price", 0))
            if entry_price > 0:
                try:
                    acct = self.get_account()
                    equity = float(acct.get("equity", 0))
                    quantity = (equity * position_size_pct) / entry_price
                except Exception:
                    pass
        if quantity <= 0:
            return {"success": False, "error": "Could not determine order quantity"}

        # Prices
        entry_price = float(rec_dict.get("entry_price", 0))
        if limit_price is None and order_type in (OrderType.LIMIT, OrderType.STOP_LIMIT):
            limit_price = entry_price if entry_price > 0 else None
        if stop_price is None and order_type in (OrderType.STOP, OrderType.STOP_LIMIT):
            stop_price = float(rec_dict.get("stop_loss", 0)) or None

        # Build order
        order = BrokerOrder(
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price,
            stop_price=stop_price,
            time_in_force=time_in_force,
            client_id=f"ti-{uuid.uuid4().hex[:8]}",
            reasoning=rec_dict.get("reasoning", ""),
            recommendation_id=rec_dict.get("timestamp", ""),
        )

        # Approval gate
        should_approve = auto_approve if auto_approve is not None else (
            self._config.mode == TradingMode.PAPER or not self._config.require_approval
        )

        if should_approve:
            order.approval_status = ApprovalStatus.AUTO_APPROVED
        else:
            order.approval_status = ApprovalStatus.PENDING
            self._pending_approvals.append(order)
            return {
                "success": True,
                "pending_approval": True,
                "order": order.to_dict(),
                "message": "Order pending human approval",
            }

        # Submit to broker
        return self._execute_order(order)

    def approve_order(self, client_id: str) -> Dict[str, Any]:
        """Approve a pending order (human approval gate).

        Args:
            client_id: The client order ID to approve.

        Returns:
            Result dictionary.
        """
        for order in self._pending_approvals:
            if order.client_id == client_id:
                order.approval_status = ApprovalStatus.APPROVED
                self._pending_approvals.remove(order)
                return self._execute_order(order)

        return {"success": False, "error": f"No pending order with client_id: {client_id}"}

    def reject_order(self, client_id: str, reason: str = "Rejected by user") -> Dict[str, Any]:
        """Reject a pending order.

        Args:
            client_id: The client order ID to reject.
            reason: Rejection reason.

        Returns:
            Result dictionary.
        """
        for order in self._pending_approvals:
            if order.client_id == client_id:
                order.approval_status = ApprovalStatus.REJECTED
                order.status = OrderStatus.REJECTED
                order.reasoning = reason
                self._pending_approvals.remove(order)
                self._order_history.append(order)
                return {"success": True, "order": order.to_dict(), "message": reason}

        return {"success": False, "error": f"No pending order with client_id: {client_id}"}

    def _execute_order(self, order: BrokerOrder) -> Dict[str, Any]:
        """Submit an approved order to the Alpaca API."""
        if not self._connected or self._client is None:
            return {"success": False, "error": "Not connected to broker. Call connect() first."}

        try:
            from alpaca.trading.requests import (
                LimitOrderRequest,
                MarketOrderRequest,
                StopLimitOrderRequest,
                StopOrderRequest,
            )
            from alpaca.trading.enums import OrderSide as AlpacaSide
            from alpaca.trading.enums import TimeInForce

            side_map = {OrderSide.BUY: AlpacaSide.BUY, OrderSide.SELL: AlpacaSide.SELL}
            tif_map = {
                "day": TimeInForce.DAY,
                "gtc": TimeInForce.GTC,
                "opg": TimeInForce.OPG,
                "ioc": TimeInForce.IOC,
                "fok": TimeInForce.FOK,
            }
            tif = tif_map.get(order.time_in_force, TimeInForce.DAY)

            # Round quantity to 2 decimal places (Alpaca requirement for fractional)
            qty = round(order.quantity, 2)

            req: Any = None
            if order.order_type == OrderType.MARKET:
                req = MarketOrderRequest(
                    symbol=order.symbol,
                    qty=qty,
                    side=side_map[order.side],
                    time_in_force=tif,
                    client_order_id=order.client_id,
                )
            elif order.order_type == OrderType.LIMIT:
                if order.limit_price is None:
                    return {"success": False, "error": "Limit order requires a limit_price"}
                req = LimitOrderRequest(
                    symbol=order.symbol,
                    qty=qty,
                    side=side_map[order.side],
                    time_in_force=tif,
                    limit_price=order.limit_price,
                    client_order_id=order.client_id,
                )
            elif order.order_type == OrderType.STOP:
                if order.stop_price is None:
                    return {"success": False, "error": "Stop order requires a stop_price"}
                req = StopOrderRequest(
                    symbol=order.symbol,
                    qty=qty,
                    side=side_map[order.side],
                    time_in_force=tif,
                    stop_price=order.stop_price,
                    client_order_id=order.client_id,
                )
            elif order.order_type == OrderType.STOP_LIMIT:
                if order.limit_price is None or order.stop_price is None:
                    return {"success": False, "error": "Stop-limit requires both limit_price and stop_price"}
                req = StopLimitOrderRequest(
                    symbol=order.symbol,
                    qty=qty,
                    side=side_map[order.side],
                    time_in_force=tif,
                    stop_price=order.stop_price,
                    limit_price=order.limit_price,
                    client_order_id=order.client_id,
                )
            else:
                return {"success": False, "error": f"Unknown order type: {order.order_type}"}

            broker_order = self._client.submit_order(req)

            # Update our order with broker response
            order.broker_id = str(broker_order.id)
            order.status = OrderStatus.SUBMITTED
            order.submitted_at = datetime.utcnow()
            self._order_history.append(order)
            self._daily_trade_count += 1

            logger.info(
                "Order submitted: %s %s %s qty=%s @ %s (broker_id=%s)",
                order.side.value,
                order.symbol,
                order.order_type.value,
                qty,
                order.limit_price or "MKT",
                order.broker_id,
            )

            return {
                "success": True,
                "order": order.to_dict(),
                "broker_order_id": order.broker_id,
            }

        except Exception as exc:
            order.status = OrderStatus.REJECTED
            order.reasoning = str(exc)
            self._order_history.append(order)
            logger.error("Order submission failed: %s", exc)
            return {"success": False, "error": str(exc), "order": order.to_dict()}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel an open order by broker order ID.

        Args:
            order_id: Alpaca order ID.

        Returns:
            Result dictionary.
        """
        if not self._connected or self._client is None:
            return {"success": False, "error": "Not connected"}

        try:
            self._client.cancel_order_by_id(order_id)
            logger.info("Order cancelled: %s", order_id)

            # Update local tracking
            for order in self._order_history:
                if order.broker_id == order_id:
                    order.status = OrderStatus.CANCELLED
                    break

            return {"success": True, "order_id": order_id, "message": "Order cancelled"}
        except Exception as exc:
            logger.error("Cancel failed for %s: %s", order_id, exc)
            return {"success": False, "error": str(exc)}

    def cancel_all_orders(self) -> Dict[str, Any]:
        """Cancel all open orders.

        Returns:
            Result dictionary.
        """
        if not self._connected or self._client is None:
            return {"success": False, "error": "Not connected"}

        try:
            self._client.cancel_orders()
            logger.info("All orders cancelled")
            return {"success": True, "message": "All open orders cancelled"}
        except Exception as exc:
            logger.error("Cancel all failed: %s", exc)
            return {"success": False, "error": str(exc)}

    # ---- Account & Position Queries ----

    def get_account(self) -> Dict[str, Any]:
        """Get account information (balance, buying power, equity).

        Returns:
            Account information dictionary.
        """
        if not self._connected or self._client is None:
            return {"error": "Not connected"}

        try:
            acct = self._client.get_account()
            return {
                "equity": str(acct.equity),
                "cash": str(acct.cash),
                "buying_power": str(acct.buying_power),
                "portfolio_value": str(acct.portfolio_value),
                "day_trade_count": acct.daytrade_count,
                "pattern_day_trader": acct.pattern_day_trader,
                "status": str(acct.status),
                "trading_blocked": acct.trading_blocked,
                "account_blocked": acct.account_blocked,
            }
        except Exception as exc:
            logger.error("get_account failed: %s", exc)
            return {"error": str(exc)}

    def get_positions(self) -> List[Dict[str, Any]]:
        """Get all current positions from broker.

        Returns:
            List of position dictionaries.
        """
        if not self._connected or self._client is None:
            return []

        try:
            positions = self._client.get_all_positions()
            return [
                {
                    "symbol": str(p.symbol),
                    "qty": str(p.qty),
                    "side": str(p.side),
                    "avg_entry_price": str(p.avg_entry_price),
                    "current_price": str(p.current_price),
                    "market_value": str(p.market_value),
                    "unrealized_pl": str(p.unrealized_pl),
                    "unrealized_plpc": str(p.unrealized_plpc),
                }
                for p in positions
            ]
        except Exception as exc:
            logger.error("get_positions failed: %s", exc)
            return []

    def get_orders(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Get orders from the broker.

        Args:
            status: Filter by status (open, closed, all).
            limit: Max number of orders.

        Returns:
            List of order dictionaries.
        """
        if not self._connected or self._client is None:
            return []

        try:
            from alpaca.trading.requests import GetOrdersRequest

            request = GetOrdersRequest(limit=limit)
            orders = self._client.get_orders(request)
            result = []
            for o in orders:
                result.append({
                    "id": str(o.id),
                    "client_order_id": str(o.client_order_id) if o.client_order_id else "",
                    "symbol": str(o.symbol),
                    "side": str(o.side),
                    "type": str(o.type),
                    "qty": str(o.qty),
                    "filled_qty": str(o.filled_qty),
                    "filled_avg_price": str(o.filled_avg_price) if o.filled_avg_price else None,
                    "status": str(o.status),
                    "limit_price": str(o.limit_price) if o.limit_price else None,
                    "stop_price": str(o.stop_price) if o.stop_price else None,
                    "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
                    "filled_at": o.filled_at.isoformat() if o.filled_at else None,
                })
            return result
        except Exception as exc:
            logger.error("get_orders failed: %s", exc)
            return []

    # ---- Portfolio Sync ----

    def sync_portfolio(self) -> Dict[str, Any]:
        """Synchronize local portfolio state with broker positions.

        Returns:
            Sync result dictionary.
        """
        broker_positions = self.get_positions()
        # For now, local positions come from order history
        local_positions = []
        for order in self._order_history:
            if order.status in (OrderStatus.FILLED, OrderStatus.SUBMITTED):
                local_positions.append({"symbol": order.symbol})

        result = self._sync.sync(broker_positions, local_positions)
        return result.to_dict()

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get orders waiting for human approval."""
        return [o.to_dict() for o in self._pending_approvals]

    def emergency_stop(self) -> Dict[str, Any]:
        """Emergency stop: halt all trading and cancel open orders."""
        return self._emergency.emergency_stop()

    def pause_trading(self, reason: str = "manual_pause") -> Dict[str, Any]:
        """Pause new trading."""
        return self._emergency.pause_trading(reason)

    def resume_trading(self) -> Dict[str, Any]:
        """Resume trading."""
        return self._emergency.resume_trading()

    def record_trade_result(self, pnl: float) -> Optional[Dict[str, Any]]:
        """Record a completed trade result and check circuit breaker."""
        self._daily_pnl += pnl
        return self._emergency.record_trade_result(pnl)

    def get_status(self) -> Dict[str, Any]:
        """Get full broker status."""
        return {
            "connected": self._connected,
            "mode": self._config.mode.value,
            "config": self._config.to_dict(),
            "emergency": self._emergency.get_status(),
            "daily_trade_count": self._daily_trade_count,
            "daily_pnl": self._daily_pnl,
            "pending_approvals": len(self._pending_approvals),
            "order_history_count": len(self._order_history),
        }


# ---- CLI ----

def main() -> None:
    """CLI entry point for the broker module."""
    parser = argparse.ArgumentParser(description="Alpaca Broker Integration")
    parser.add_argument("--account-status", action="store_true", help="Show account status")
    parser.add_argument("--positions", action="store_true", help="Show current positions")
    parser.add_argument("--orders", action="store_true", help="Show recent orders")
    parser.add_argument("--broker-status", action="store_true", help="Show broker system status")
    parser.add_argument("--emergency-stop", action="store_true", help="Activate emergency stop")
    parser.add_argument("--pause", action="store_true", help="Pause trading")
    parser.add_argument("--resume", action="store_true", help="Resume trading")

    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    broker = AlpacaBroker()

    if args.emergency_stop:
        result = broker.emergency_stop()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.pause:
        result = broker.pause_trading()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.resume:
        result = broker.resume_trading()
        print(json.dumps(result, indent=2, default=str))
        return

    if args.broker_status:
        print(json.dumps(broker.get_status(), indent=2, default=str))
        return

    # These require a connection
    connect_result = broker.connect()
    if not connect_result.get("connected"):
        print(json.dumps(connect_result, indent=2))
        return

    if args.account_status:
        acct = broker.get_account()
        print(json.dumps(acct, indent=2, default=str))
    elif args.positions:
        positions = broker.get_positions()
        print(json.dumps(positions, indent=2, default=str))
    elif args.orders:
        orders = broker.get_orders()
        print(json.dumps(orders, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
