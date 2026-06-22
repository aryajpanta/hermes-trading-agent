"""Tests for broker integration — M8.

Tests cover:
- ExecutionConfig loading and safety gates
- Order models (BrokerOrder creation, serialization)
- Emergency controls (stop, pause, resume, circuit breaker)
- Portfolio sync
- AlpacaBroker (with mocked Alpaca client)
- Approval flow
- CLI command parsing
"""

import json
import os
import sys
from datetime import datetime, date
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root on path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from src.execution.broker import AlpacaBroker, ExecutionConfig, TradingMode
from src.execution.orders import (
    ApprovalStatus,
    BrokerOrder,
    OrderSide,
    OrderStatus,
    OrderType,
)
from src.execution.emergency import EmergencyController, EmergencyState
from src.execution.sync import BrokerPosition, PortfolioSync, SyncResult
from src.decision.models import Direction, TradeRecommendation


# ---- ExecutionConfig Tests ----


class TestExecutionConfig:
    """Tests for ExecutionConfig safety gate dataclass."""

    def test_default_config(self) -> None:
        config = ExecutionConfig()
        assert config.mode == TradingMode.PAPER
        assert config.require_approval is True
        assert config.max_daily_trades == 10
        assert config.max_daily_loss_pct == 0.02
        assert config.emergency_stop is False

    def test_config_from_dict(self) -> None:
        config = ExecutionConfig(
            mode=TradingMode.LIVE,
            require_approval=False,
            max_daily_trades=20,
            max_daily_loss_pct=0.05,
        )
        assert config.mode == TradingMode.LIVE
        assert config.require_approval is False
        assert config.max_daily_trades == 20

    def test_config_to_dict(self) -> None:
        config = ExecutionConfig()
        d = config.to_dict()
        assert d["mode"] == "PAPER"
        assert d["require_approval"] is True
        assert d["max_daily_trades"] == 10

    def test_config_from_yaml(self, tmp_path: Any) -> None:
        yaml_content = """
execution:
  mode: LIVE
  require_approval: false
  max_daily_trades: 5
  max_daily_loss_pct: 0.03
  emergency_stop: true
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        config = ExecutionConfig.from_yaml(str(config_file))
        assert config.mode == TradingMode.LIVE
        assert config.require_approval is False
        assert config.max_daily_trades == 5
        assert config.max_daily_loss_pct == 0.03
        assert config.emergency_stop is True

    def test_config_from_yaml_invalid_mode(self, tmp_path: Any) -> None:
        yaml_content = """
execution:
  mode: INVALID
"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text(yaml_content)

        config = ExecutionConfig.from_yaml(str(config_file))
        # Invalid mode defaults to PAPER
        assert config.mode == TradingMode.PAPER


# ---- Order Model Tests ----


class TestBrokerOrder:
    """Tests for BrokerOrder data model."""

    def test_default_order(self) -> None:
        order = BrokerOrder()
        assert order.symbol == ""
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.quantity == 0.0
        assert order.status == OrderStatus.PENDING
        assert order.approval_status == ApprovalStatus.PENDING

    def test_order_to_dict(self) -> None:
        order = BrokerOrder(
            symbol="AAPL",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=10.0,
            limit_price=150.0,
            broker_id="test-123",
            client_id="ti-abc",
        )
        d = order.to_dict()
        assert d["symbol"] == "AAPL"
        assert d["side"] == "buy"
        assert d["order_type"] == "limit"
        assert d["quantity"] == 10.0
        assert d["limit_price"] == 150.0
        assert d["broker_id"] == "test-123"
        assert d["client_id"] == "ti-abc"

    def test_order_from_broker_response(self) -> None:
        response = {
            "id": "broker-001",
            "client_order_id": "ti-test",
            "symbol": "TSLA",
            "side": "buy",
            "type": "limit",
            "qty": "5",
            "limit_price": "200.00",
            "stop_price": None,
            "time_in_force": "day",
            "status": "filled",
            "filled_qty": "5",
            "filled_avg_price": "199.50",
            "submitted_at": "2025-01-01T12:00:00Z",
            "filled_at": "2025-01-01T12:00:05Z",
        }
        order = BrokerOrder.from_broker_response(response)
        assert order.broker_id == "broker-001"
        assert order.symbol == "TSLA"
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.quantity == 5.0
        assert order.limit_price == 200.0
        assert order.status == OrderStatus.FILLED
        assert order.filled_price == 199.5
        assert order.filled_quantity == 5.0

    def test_order_all_types(self) -> None:
        for otype in OrderType:
            order = BrokerOrder(order_type=otype)
            assert order.order_type == otype


class TestOrderEnums:
    """Tests for order enum types."""

    def test_order_type_values(self) -> None:
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"
        assert OrderType.STOP_LIMIT.value == "stop_limit"

    def test_order_side_values(self) -> None:
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"

    def test_order_status_values(self) -> None:
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"

    def test_approval_status_values(self) -> None:
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.AUTO_APPROVED.value == "auto_approved"


# ---- Emergency Controller Tests ----


class TestEmergencyController:
    """Tests for emergency stop, pause, resume, and circuit breaker."""

    def test_initial_state(self) -> None:
        ctrl = EmergencyController()
        assert ctrl.is_trading_allowed() is True
        assert ctrl.state.emergency_stop is False
        assert ctrl.state.trading_paused is False
        assert ctrl.state.consecutive_losses == 0
        assert ctrl.state.circuit_breaker_active is False

    def test_emergency_stop(self) -> None:
        ctrl = EmergencyController()
        result = ctrl.emergency_stop()
        assert result["success"] is True
        assert result["action"] == "emergency_stop"
        assert ctrl.state.emergency_stop is True
        assert ctrl.state.trading_paused is True
        assert ctrl.is_trading_allowed() is False

    def test_emergency_stop_callback(self) -> None:
        ctrl = EmergencyController()
        callback_called = []
        ctrl.set_emergency_stop_callback(lambda: callback_called.append(True))
        ctrl.emergency_stop()
        assert len(callback_called) == 1

    def test_emergency_stop_callback_exception(self) -> None:
        """Callback failure should not prevent emergency stop."""
        ctrl = EmergencyController()
        ctrl.set_emergency_stop_callback(lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        result = ctrl.emergency_stop()
        assert result["success"] is True

    def test_pause_trading(self) -> None:
        ctrl = EmergencyController()
        result = ctrl.pause_trading("testing")
        assert result["success"] is True
        assert ctrl.state.trading_paused is True
        assert ctrl.state.pause_reason == "testing"
        assert ctrl.is_trading_allowed() is False

    def test_resume_trading(self) -> None:
        ctrl = EmergencyController()
        ctrl.pause_trading("test")
        result = ctrl.resume_trading()
        assert result["success"] is True
        assert ctrl.state.trading_paused is False
        assert ctrl.is_trading_allowed() is True

    def test_resume_fails_with_emergency_stop(self) -> None:
        ctrl = EmergencyController()
        ctrl.emergency_stop()
        result = ctrl.resume_trading()
        assert result["success"] is False
        assert "emergency stop" in result["message"].lower()

    def test_resume_fails_with_circuit_breaker(self) -> None:
        ctrl = EmergencyController()
        # Trigger circuit breaker with 3 losses
        for _ in range(3):
            ctrl.record_trade_result(-10.0)
        result = ctrl.resume_trading()
        assert result["success"] is False
        assert "circuit breaker" in result["message"].lower()

    def test_circuit_breaker_not_triggered_under_threshold(self) -> None:
        ctrl = EmergencyController(circuit_breaker_threshold=3)
        for _ in range(2):
            result = ctrl.record_trade_result(-10.0)
            assert result is None
        assert ctrl.is_trading_allowed() is True
        assert ctrl.state.consecutive_losses == 2

    def test_circuit_breaker_triggered(self) -> None:
        ctrl = EmergencyController(circuit_breaker_threshold=3)
        for _ in range(2):
            ctrl.record_trade_result(-10.0)
        result = ctrl.record_trade_result(-10.0)
        assert result is not None
        assert result["action"] == "circuit_breaker"
        assert ctrl.state.circuit_breaker_active is True
        assert ctrl.state.trading_paused is True

    def test_circuit_breaker_resets_on_win(self) -> None:
        ctrl = EmergencyController(circuit_breaker_threshold=3)
        ctrl.record_trade_result(-10.0)
        ctrl.record_trade_result(-10.0)
        # Win resets the counter
        ctrl.record_trade_result(20.0)
        assert ctrl.state.consecutive_losses == 0
        assert ctrl.is_trading_allowed() is True

    def test_reset_emergency_stop(self) -> None:
        ctrl = EmergencyController()
        ctrl.emergency_stop()
        result = ctrl.reset_emergency_stop()
        assert result["success"] is True
        assert ctrl.state.emergency_stop is False

    def test_reset_circuit_breaker(self) -> None:
        ctrl = EmergencyController(circuit_breaker_threshold=3)
        for _ in range(3):
            ctrl.record_trade_result(-10.0)
        ctrl.reset_circuit_breaker()
        assert ctrl.state.circuit_breaker_active is False
        assert ctrl.state.consecutive_losses == 0
        assert ctrl.state.trading_paused is False

    def test_emergency_state_to_dict(self) -> None:
        state = EmergencyState()
        d = state.to_dict()
        assert "emergency_stop" in d
        assert "trading_paused" in d
        assert "consecutive_losses" in d

    def test_get_status(self) -> None:
        ctrl = EmergencyController()
        status = ctrl.get_status()
        assert "state" in status
        assert "trading_allowed" in status
        assert status["trading_allowed"] is True

    def test_custom_threshold(self) -> None:
        ctrl = EmergencyController(circuit_breaker_threshold=1)
        result = ctrl.record_trade_result(-10.0)
        assert result is not None
        assert result["action"] == "circuit_breaker"


# ---- Portfolio Sync Tests ----


class TestPortfolioSync:
    """Tests for portfolio synchronization."""

    def test_initial_sync(self) -> None:
        sync = PortfolioSync()
        result = sync.sync([], [])
        assert isinstance(result, SyncResult)
        assert result.added == []
        assert result.removed == []
        assert result.unchanged == []

    def test_matching_positions(self) -> None:
        sync = PortfolioSync()
        broker = [{"symbol": "AAPL", "qty": "10", "avg_entry_price": "150"}]
        local = [{"symbol": "AAPL"}]
        result = sync.sync(broker, local)
        assert "AAPL" in result.unchanged

    def test_broker_has_extra(self) -> None:
        sync = PortfolioSync()
        broker = [
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "150"},
            {"symbol": "TSLA", "qty": "5", "avg_entry_price": "200"},
        ]
        local = [{"symbol": "AAPL"}]
        result = sync.sync(broker, local)
        assert "TSLA" in result.added
        assert len(result.added) == 1

    def test_local_has_extra(self) -> None:
        sync = PortfolioSync()
        broker = [{"symbol": "AAPL", "qty": "10", "avg_entry_price": "150"}]
        local = [{"symbol": "AAPL"}, {"symbol": "GOOGL"}]
        result = sync.sync(broker, local)
        assert "GOOGL" in result.removed
        assert len(result.removed) == 1

    def test_sync_result_to_dict(self) -> None:
        sync = PortfolioSync()
        result = sync.sync([], [])
        d = result.to_dict()
        assert "broker_positions" in d
        assert "added" in d
        assert "removed" in d
        assert "synced_at" in d

    def test_broker_position_from_dict(self) -> None:
        data = {
            "symbol": "MSFT",
            "qty": "20",
            "avg_entry_price": "300.0",
            "current_price": "310.0",
            "unrealized_pl": "200.0",
            "unrealized_plpc": "0.0333",
            "market_value": "6200.0",
            "side": "long",
        }
        bp = BrokerPosition.from_broker(data)
        assert bp.symbol == "MSFT"
        assert bp.quantity == 20.0
        assert bp.unrealized_pnl == 200.0

    def test_get_last_sync(self) -> None:
        sync = PortfolioSync()
        assert sync.last_sync is None
        sync.sync([], [])
        assert sync.last_sync is not None

    def test_get_total_unrealized_pnl(self) -> None:
        sync = PortfolioSync()
        broker = [
            {"symbol": "AAPL", "qty": "10", "avg_entry_price": "150", "unrealized_pl": "50.0"},
            {"symbol": "TSLA", "qty": "5", "avg_entry_price": "200", "unrealized_pl": "-30.0"},
        ]
        sync.sync(broker, [])
        assert sync.get_total_unrealized_pnl() == 20.0


# ---- Broker Tests (Mocked) ----


class TestAlpacaBroker:
    """Tests for AlpacaBroker with mocked Alpaca client."""

    def _make_broker(self, **kwargs: Any) -> AlpacaBroker:
        """Create a broker with a mocked client."""
        config = kwargs.pop("config", ExecutionConfig(mode=TradingMode.PAPER, require_approval=False))
        broker = AlpacaBroker(config=config, **kwargs)
        broker._connected = True
        broker._client = MagicMock()
        return broker

    def test_initial_state(self) -> None:
        broker = AlpacaBroker()
        assert broker.connected is False
        assert broker.config.mode == TradingMode.PAPER

    def test_connect_success(self) -> None:
        broker = AlpacaBroker(api_key="test", secret_key="test")
        with patch("alpaca.trading.client.TradingClient") as mock_tc:
            mock_tc.return_value = MagicMock()
            result = broker.connect(api_key="test", secret_key="test")
            assert result["connected"] is True

    def test_connect_missing_keys(self) -> None:
        broker = AlpacaBroker()
        result = broker.connect()
        assert result["connected"] is False
        assert "Missing" in result["error"]

    def test_get_account(self) -> None:
        broker = self._make_broker()
        mock_acct = MagicMock()
        mock_acct.equity = 100000
        mock_acct.cash = 50000
        mock_acct.buying_power = 100000
        mock_acct.portfolio_value = 100000
        mock_acct.daytrade_count = 2
        mock_acct.pattern_day_trader = False
        mock_acct.status = "ACTIVE"
        mock_acct.trading_blocked = False
        mock_acct.account_blocked = False
        broker._client.get_account.return_value = mock_acct

        result = broker.get_account()
        assert result["equity"] == "100000"
        assert result["cash"] == "50000"

    def test_get_positions(self) -> None:
        broker = self._make_broker()
        mock_pos = MagicMock()
        mock_pos.symbol = "AAPL"
        mock_pos.qty = "10"
        mock_pos.side = "long"
        mock_pos.avg_entry_price = "150.0"
        mock_pos.current_price = "155.0"
        mock_pos.market_value = "1550.0"
        mock_pos.unrealized_pl = "50.0"
        mock_pos.unrealized_plpc = "0.0333"
        broker._client.get_all_positions.return_value = [mock_pos]

        result = broker.get_positions()
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    def test_get_orders(self) -> None:
        broker = self._make_broker()
        mock_order = MagicMock()
        mock_order.id = "order-1"
        mock_order.client_order_id = "ti-test"
        mock_order.symbol = "AAPL"
        mock_order.side = "buy"
        mock_order.type = "limit"
        mock_order.qty = "10"
        mock_order.filled_qty = "0"
        mock_order.filled_avg_price = None
        mock_order.status = "new"
        mock_order.limit_price = "150.0"
        mock_order.stop_price = None
        mock_order.submitted_at = datetime(2025, 1, 1, 12, 0, 0)
        mock_order.filled_at = None
        broker._client.get_orders.return_value = [mock_order]

        result = broker.get_orders()
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"

    def test_submit_market_order_paper_mode(self) -> None:
        broker = self._make_broker(config=ExecutionConfig(
            mode=TradingMode.PAPER, require_approval=False
        ))
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-001"
        broker._client.submit_order.return_value = mock_broker_order

        # Mock account for quantity calculation
        mock_acct = MagicMock()
        mock_acct.equity = 100000
        broker._client.get_account.return_value = mock_acct

        result = broker.submit_order(
            recommendation={
                "symbol": "AAPL",
                "direction": "BUY",
                "quantity": 10,
                "entry_price": 150.0,
                "reasoning": "Test trade",
            },
            order_type=OrderType.MARKET,
            auto_approve=True,
        )
        assert result["success"] is True
        assert "broker_order_id" in result

    def test_submit_limit_order(self) -> None:
        broker = self._make_broker()
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-002"
        broker._client.submit_order.return_value = mock_broker_order

        result = broker.submit_order(
            recommendation={
                "symbol": "TSLA",
                "direction": "BUY",
                "quantity": 5,
                "entry_price": 200.0,
            },
            order_type=OrderType.LIMIT,
            limit_price=195.0,
            auto_approve=True,
        )
        assert result["success"] is True

    def test_submit_stop_order(self) -> None:
        broker = self._make_broker()
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-003"
        broker._client.submit_order.return_value = mock_broker_order

        result = broker.submit_order(
            recommendation={
                "symbol": "MSFT",
                "direction": "SELL",
                "quantity": 10,
                "entry_price": 300.0,
            },
            order_type=OrderType.STOP,
            stop_price=310.0,
            auto_approve=True,
        )
        assert result["success"] is True

    def test_submit_stop_limit_order(self) -> None:
        broker = self._make_broker()
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-004"
        broker._client.submit_order.return_value = mock_broker_order

        result = broker.submit_order(
            recommendation={
                "symbol": "NVDA",
                "direction": "BUY",
                "quantity": 5,
                "entry_price": 500.0,
            },
            order_type=OrderType.STOP_LIMIT,
            limit_price=495.0,
            stop_price=490.0,
            auto_approve=True,
        )
        assert result["success"] is True

    def test_submit_order_with_trade_recommendation(self) -> None:
        """Test submission using a TradeRecommendation object."""
        broker = self._make_broker()
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-005"
        broker._client.submit_order.return_value = mock_broker_order

        # Mock account for quantity calculation from position_size_pct
        mock_acct = MagicMock()
        mock_acct.equity = 100000
        broker._client.get_account.return_value = mock_acct

        rec = TradeRecommendation(
            symbol="AAPL",
            direction=Direction.BUY,
            confidence=0.8,
            entry_price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            position_size_pct=0.05,
            reasoning="Strong signal",
        )
        result = broker.submit_order(recommendation=rec, auto_approve=True)
        assert result["success"] is True

    def test_approval_flow_pending(self) -> None:
        """Live mode requires approval — order should be pending."""
        config = ExecutionConfig(mode=TradingMode.LIVE, require_approval=True)
        broker = self._make_broker(config=config)

        result = broker.submit_order(
            recommendation={
                "symbol": "AAPL",
                "direction": "BUY",
                "quantity": 10,
                "entry_price": 150.0,
            },
            order_type=OrderType.MARKET,
        )
        assert result["success"] is True
        assert result.get("pending_approval") is True
        assert len(broker.get_pending_approvals()) == 1

    def test_approval_flow_approve(self) -> None:
        config = ExecutionConfig(mode=TradingMode.LIVE, require_approval=True)
        broker = self._make_broker(config=config)
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-approved"
        broker._client.submit_order.return_value = mock_broker_order

        # Submit (pending)
        result = broker.submit_order(
            recommendation={
                "symbol": "AAPL",
                "direction": "BUY",
                "quantity": 10,
                "entry_price": 150.0,
            },
            order_type=OrderType.MARKET,
        )
        client_id = result["order"]["client_id"]

        # Approve
        approve_result = broker.approve_order(client_id)
        assert approve_result["success"] is True
        assert "broker_order_id" in approve_result
        assert len(broker.get_pending_approvals()) == 0

    def test_approval_flow_reject(self) -> None:
        config = ExecutionConfig(mode=TradingMode.LIVE, require_approval=True)
        broker = self._make_broker(config=config)

        result = broker.submit_order(
            recommendation={
                "symbol": "AAPL",
                "direction": "BUY",
                "quantity": 10,
                "entry_price": 150.0,
            },
            order_type=OrderType.MARKET,
        )
        client_id = result["order"]["client_id"]

        reject_result = broker.reject_order(client_id, "Too risky")
        assert reject_result["success"] is True
        assert len(broker.get_pending_approvals()) == 0

    def test_reject_nonexistent_order(self) -> None:
        broker = self._make_broker()
        result = broker.reject_order("nonexistent")
        assert result["success"] is False

    def test_approve_nonexistent_order(self) -> None:
        broker = self._make_broker()
        result = broker.approve_order("nonexistent")
        assert result["success"] is False

    def test_cancel_order(self) -> None:
        broker = self._make_broker()
        result = broker.cancel_order("order-123")
        assert result["success"] is True
        broker._client.cancel_order_by_id.assert_called_once_with("order-123")

    def test_cancel_all_orders(self) -> None:
        broker = self._make_broker()
        result = broker.cancel_all_orders()
        assert result["success"] is True
        broker._client.cancel_orders.assert_called_once()

    def test_cancel_order_not_connected(self) -> None:
        broker = AlpacaBroker()
        result = broker.cancel_order("order-123")
        assert result["success"] is False

    def test_sync_portfolio(self) -> None:
        broker = self._make_broker()
        mock_pos = MagicMock()
        mock_pos.symbol = "AAPL"
        mock_pos.qty = "10"
        mock_pos.side = "long"
        mock_pos.avg_entry_price = "150.0"
        mock_pos.current_price = "155.0"
        mock_pos.market_value = "1550.0"
        mock_pos.unrealized_pl = "50.0"
        mock_pos.unrealized_plpc = "0.0333"
        broker._client.get_all_positions.return_value = [mock_pos]

        result = broker.sync_portfolio()
        assert "added" in result
        assert "broker_positions" in result

    def test_emergency_stop(self) -> None:
        broker = self._make_broker()
        broker._client.cancel_orders = MagicMock()
        result = broker.emergency_stop()
        assert result["success"] is True
        assert broker.emergency.state.emergency_stop is True

    def test_pause_trading(self) -> None:
        broker = self._make_broker()
        result = broker.pause_trading("testing")
        assert result["success"] is True
        assert not broker.emergency.is_trading_allowed()

    def test_resume_trading(self) -> None:
        broker = self._make_broker()
        broker.pause_trading("test")
        result = broker.resume_trading()
        assert result["success"] is True
        assert broker.emergency.is_trading_allowed()

    def test_record_trade_result(self) -> None:
        broker = self._make_broker()
        # Win
        result = broker.record_trade_result(100.0)
        assert result is None
        assert broker._daily_pnl == 100.0

    def test_circuit_breaker_via_broker(self) -> None:
        broker = self._make_broker()
        broker._client.cancel_orders = MagicMock()
        for _ in range(2):
            broker.record_trade_result(-50.0)
        result = broker.record_trade_result(-50.0)
        assert result is not None
        assert result["action"] == "circuit_breaker"

    def test_safety_gate_emergency_stop(self) -> None:
        config = ExecutionConfig(emergency_stop=True)
        broker = self._make_broker(config=config)
        result = broker.submit_order(
            recommendation={"symbol": "AAPL", "direction": "BUY", "quantity": 10, "entry_price": 150.0},
            auto_approve=True,
        )
        assert result["success"] is False
        assert "Emergency" in result["error"]

    def test_safety_gate_max_daily_trades(self) -> None:
        config = ExecutionConfig(max_daily_trades=2, require_approval=False)
        broker = self._make_broker(config=config)
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-trades"
        broker._client.submit_order.return_value = mock_broker_order

        for _ in range(2):
            broker.submit_order(
                recommendation={"symbol": "AAPL", "direction": "BUY", "quantity": 1, "entry_price": 100},
                auto_approve=True,
            )

        result = broker.submit_order(
            recommendation={"symbol": "AAPL", "direction": "BUY", "quantity": 1, "entry_price": 100},
            auto_approve=True,
        )
        assert result["success"] is False
        assert "Daily trade limit" in result["error"]

    def test_missing_symbol(self) -> None:
        broker = self._make_broker()
        result = broker.submit_order(
            recommendation={"direction": "BUY", "quantity": 10},
            auto_approve=True,
        )
        assert result["success"] is False
        assert "Missing symbol" in result["error"]

    def test_unknown_direction(self) -> None:
        broker = self._make_broker()
        result = broker.submit_order(
            recommendation={"symbol": "AAPL", "direction": "HOLD", "quantity": 10},
            auto_approve=True,
        )
        assert result["success"] is False
        assert "Unknown direction" in result["error"]

    def test_get_status(self) -> None:
        broker = self._make_broker()
        status = broker.get_status()
        assert status["connected"] is True
        assert status["mode"] == "PAPER"
        assert "config" in status
        assert "emergency" in status

    def test_not_connected_get_account(self) -> None:
        broker = AlpacaBroker()
        result = broker.get_account()
        assert "error" in result

    def test_not_connected_get_positions(self) -> None:
        broker = AlpacaBroker()
        result = broker.get_positions()
        assert result == []

    def test_order_history_tracking(self) -> None:
        broker = self._make_broker()
        mock_broker_order = MagicMock()
        mock_broker_order.id = "broker-hist"
        broker._client.submit_order.return_value = mock_broker_order

        broker.submit_order(
            recommendation={"symbol": "AAPL", "direction": "BUY", "quantity": 10, "entry_price": 150},
            auto_approve=True,
        )
        assert len(broker._order_history) == 1
        assert broker._order_history[0].broker_id == "broker-hist"

    def test_daily_trade_count_resets(self) -> None:
        config = ExecutionConfig(max_daily_trades=100, require_approval=False)
        broker = self._make_broker(config=config)
        broker._daily_trade_count = 5
        broker._daily_trades_date = date(2020, 1, 1)  # Old date

        mock_broker_order = MagicMock()
        mock_broker_order.id = "reset-test"
        broker._client.submit_order.return_value = mock_broker_order

        broker.submit_order(
            recommendation={"symbol": "AAPL", "direction": "BUY", "quantity": 1, "entry_price": 100},
            auto_approve=True,
        )
        assert broker._daily_trade_count == 1  # Reset then incremented
