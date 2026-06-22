"""Emergency controls and circuit breaker for broker integration.

Provides:
- Emergency stop: cancel all open orders, close all positions
- Pause/resume trading
- Circuit breaker: auto-pause on consecutive losses
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

CIRCUIT_BREAKER_THRESHOLD = 3


@dataclass
class EmergencyState:
    """Tracks the emergency/pause state of the trading system.

    Attributes:
        emergency_stop: Whether the kill switch is active.
        trading_paused: Whether new trades are paused.
        consecutive_losses: Count of recent consecutive losing trades.
        circuit_breaker_active: Whether circuit breaker tripped.
        last_updated: Timestamp of last state change.
        pause_reason: Why trading was paused.
    """

    emergency_stop: bool = False
    trading_paused: bool = False
    consecutive_losses: int = 0
    circuit_breaker_active: bool = False
    last_updated: Optional[datetime] = None
    pause_reason: str = ""

    def to_dict(self) -> Dict[str, object]:
        """Serialize state."""
        return {
            "emergency_stop": self.emergency_stop,
            "trading_paused": self.trading_paused,
            "consecutive_losses": self.consecutive_losses,
            "circuit_breaker_active": self.circuit_breaker_active,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "pause_reason": self.pause_reason,
        }


class EmergencyController:
    """Manages emergency stop, pause/resume, and circuit breaker logic.

    Args:
        circuit_breaker_threshold: Number of consecutive losses before
            auto-pausing. Defaults to 3.
    """

    def __init__(self, circuit_breaker_threshold: int = CIRCUIT_BREAKER_THRESHOLD) -> None:
        self.state = EmergencyState()
        self._threshold = circuit_breaker_threshold
        self._on_emergency_stop: Optional[Callable[[], None]] = None

    def set_emergency_stop_callback(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when emergency stop is triggered."""
        self._on_emergency_stop = callback

    def is_trading_allowed(self) -> bool:
        """Check whether new trades are currently allowed."""
        if self.state.emergency_stop:
            return False
        if self.state.trading_paused:
            return False
        if self.state.circuit_breaker_active:
            return False
        return True

    def emergency_stop(self) -> Dict[str, object]:
        """Activate the kill switch — stops all trading immediately.

        Returns:
            Dictionary with the action taken.
        """
        logger.critical("EMERGENCY STOP ACTIVATED")
        self.state.emergency_stop = True
        self.state.trading_paused = True
        self.state.circuit_breaker_active = True
        self.state.last_updated = datetime.utcnow()
        self.state.pause_reason = "emergency_stop"

        if self._on_emergency_stop:
            try:
                self._on_emergency_stop()
            except Exception as exc:
                logger.error("Emergency stop callback failed: %s", exc)

        return {
            "action": "emergency_stop",
            "success": True,
            "message": "All trading halted. All open orders should be cancelled "
            "and positions closed.",
            "state": self.state.to_dict(),
        }

    def pause_trading(self, reason: str = "manual_pause") -> Dict[str, object]:
        """Pause new trades while keeping existing positions.

        Args:
            reason: Why trading is being paused.

        Returns:
            Dictionary with the action taken.
        """
        logger.warning("Trading paused: %s", reason)
        self.state.trading_paused = True
        self.state.pause_reason = reason
        self.state.last_updated = datetime.utcnow()

        return {
            "action": "pause_trading",
            "success": True,
            "message": f"Trading paused: {reason}",
            "state": self.state.to_dict(),
        }

    def resume_trading(self) -> Dict[str, object]:
        """Resume normal trading operation.

        Note: Does NOT resume if emergency_stop or circuit_breaker is active.
        Those must be explicitly reset.

        Returns:
            Dictionary with the action taken.
        """
        if self.state.emergency_stop:
            return {
                "action": "resume_trading",
                "success": False,
                "message": "Cannot resume: emergency stop is active. "
                "Call reset_emergency_stop() first.",
                "state": self.state.to_dict(),
            }

        if self.state.circuit_breaker_active:
            return {
                "action": "resume_trading",
                "success": False,
                "message": "Cannot resume: circuit breaker is active. "
                "Call reset_circuit_breaker() first.",
                "state": self.state.to_dict(),
            }

        logger.info("Trading resumed")
        self.state.trading_paused = False
        self.state.pause_reason = ""
        self.state.last_updated = datetime.utcnow()

        return {
            "action": "resume_trading",
            "success": True,
            "message": "Trading resumed.",
            "state": self.state.to_dict(),
        }

    def record_trade_result(self, pnl: float) -> Optional[Dict[str, object]]:
        """Record a trade result and check the circuit breaker.

        Args:
            pnl: Profit/loss of the completed trade (positive = profit).

        Returns:
            Dictionary with circuit breaker action if tripped, else None.
        """
        if pnl < 0:
            self.state.consecutive_losses += 1
            logger.info(
                "Loss recorded. Consecutive losses: %d/%d",
                self.state.consecutive_losses,
                self._threshold,
            )

            if self.state.consecutive_losses >= self._threshold:
                logger.warning(
                    "Circuit breaker tripped after %d consecutive losses",
                    self.state.consecutive_losses,
                )
                self.state.circuit_breaker_active = True
                self.state.trading_paused = True
                self.state.pause_reason = (
                    f"circuit_breaker: {self.state.consecutive_losses} consecutive losses"
                )
                self.state.last_updated = datetime.utcnow()

                return {
                    "action": "circuit_breaker",
                    "success": True,
                    "message": (
                        f"Circuit breaker tripped: "
                        f"{self.state.consecutive_losses} consecutive losses."
                    ),
                    "consecutive_losses": self.state.consecutive_losses,
                    "state": self.state.to_dict(),
                }
        else:
            # Win or break-even resets the counter
            if self.state.consecutive_losses > 0:
                logger.info(
                    "Consecutive loss streak broken at %d",
                    self.state.consecutive_losses,
                )
            self.state.consecutive_losses = 0

        return None

    def reset_emergency_stop(self) -> Dict[str, object]:
        """Reset the emergency stop (requires explicit action)."""
        logger.info("Emergency stop reset")
        self.state.emergency_stop = False
        self.state.last_updated = datetime.utcnow()
        return {"action": "reset_emergency_stop", "success": True}

    def reset_circuit_breaker(self) -> Dict[str, object]:
        """Reset the circuit breaker and consecutive loss counter."""
        logger.info("Circuit breaker reset")
        self.state.circuit_breaker_active = False
        self.state.consecutive_losses = 0
        self.state.last_updated = datetime.utcnow()
        if self.state.pause_reason.startswith("circuit_breaker"):
            self.state.trading_paused = False
            self.state.pause_reason = ""
        return {"action": "reset_circuit_breaker", "success": True}

    def get_status(self) -> Dict[str, object]:
        """Get full emergency controller status."""
        return {
            "state": self.state.to_dict(),
            "trading_allowed": self.is_trading_allowed(),
            "circuit_breaker_threshold": self._threshold,
        }
