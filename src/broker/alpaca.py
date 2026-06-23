"""Thin broker facade for the unified trading system.

This module exposes a single ``BrokerConnection`` class that wraps the existing
``AlpacaBroker`` so the FastAPI layer can inject/manage a single instance
without re-implementing connection logic.
"""

import logging
import os
import threading
from typing import Any, Dict, List, Optional

from src.execution.broker import AlpacaBroker, ExecutionConfig, TradingMode

logger = logging.getLogger(__name__)

# Env var name compatibility — HTA used ALPACA_PAPER as a string "true"/"false"
def _env_paper_mode() -> bool:
    val = os.environ.get("ALPACA_PAPER", "true").lower()
    return val not in ("false", "0", "no", "off")


class BrokerConnection:
    """Singleton wrapper around AlpacaBroker for the FastAPI app.

    - Lazily creates AlpacaBroker on first access
    - Reads ALPACA_API_KEY_ID / ALPACA_SECRET_KEY / ALPACA_PAPER from env
    - Reconnect-safe: disconnect() and connect() are no-ops when already in the right state
    - Thread-safe (single global lock)
    """

    _instance: Optional["BrokerConnection"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._broker: Optional[AlpacaBroker] = None

    @classmethod
    def instance(cls) -> "BrokerConnection":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def broker(self) -> AlpacaBroker:
        if self._broker is None:
            cfg = ExecutionConfig(
                mode=TradingMode.PAPER if _env_paper_mode() else TradingMode.LIVE,
                require_approval=os.environ.get("ALPACA_REQUIRE_APPROVAL", "true").lower() not in ("false", "0"),
                max_daily_trades=int(os.environ.get("ALPACA_MAX_DAILY_TRADES", "10")),
                max_daily_loss_pct=float(os.environ.get("ALPACA_MAX_DAILY_LOSS_PCT", "0.02")),
                emergency_stop=os.environ.get("ALPACA_EMERGENCY_STOP", "false").lower() in ("true", "1"),
            )
            self._broker = AlpacaBroker(config=cfg)
        return self._broker

    def connect(self) -> Dict[str, Any]:
        if self.broker.connected:
            return {"status": "already_connected", "mode": self.broker.config.mode.value}
        return self.broker.connect()

    def disconnect(self) -> Dict[str, Any]:
        # AlpacaBroker doesn't expose disconnect; we just mark the flag
        if self._broker is not None:
            self._broker._connected = False
        return {"status": "disconnected"}

    def status(self) -> Dict[str, Any]:
        if self._broker is None or not self.broker.connected:
            return {
                "connected": False,
                "mode": "PAPER" if _env_paper_mode() else "LIVE",
                "configured": bool(os.environ.get("ALPACA_API_KEY_ID") or os.environ.get("ALPACA_API_KEY")),
            }
        return {
            "connected": True,
            "mode": self.broker.config.mode.value,
            "emergency_stop": self.broker.config.emergency_stop,
            "daily_trade_count": self.broker._daily_trade_count,
            "daily_pnl": self.broker._daily_pnl,
        }

    def get_account(self) -> Optional[Dict[str, Any]]:
        if not self.broker.connected:
            return None
        return self.broker.get_account()

    def get_positions(self) -> List[Dict[str, Any]]:
        if not self.broker.connected:
            return []
        return self.broker.get_positions()

    def get_orders(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.broker.connected:
            return []
        return self.broker.get_orders(status=status, limit=limit)

    def sync_portfolio(self) -> Dict[str, Any]:
        if not self.broker.connected:
            return {"error": "not_connected"}
        return self.broker.sync_portfolio()
