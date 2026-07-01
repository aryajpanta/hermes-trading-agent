"""Integration shim — lets the learning orchestrator subscribe to trade events
without modifying the core trading code's API.

Usage in src.automation.scheduler.run_tick (close events):
    from src.learning.integration import notify_close
    if pos.status.value != "open":
        notify_close(pos.symbol, price, pos.strategy_id)

Usage in src.execution.paper.PaperTrader._open_position (entry events):
    from src.learning.integration import notify_entry
    notify_entry(symbol, strategy_id, quantity, price)

The orchestrator is set via set_orchestrator() at app startup.
When no orchestrator is set, all notify_* calls are no-ops (zero overhead).
"""
from __future__ import annotations
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Feature flag: set LEARNER_DISABLED=1 to disable learning without code changes
_LEARNER_DISABLED = os.environ.get("LEARNER_DISABLED", "0").lower() in (
    "1", "true", "yes", "on"
)

_orchestrator: Any = None


def set_orchestrator(o: Any) -> None:
    """Wire the orchestrator. Called once at app startup."""
    global _orchestrator
    _orchestrator = o
    if o is not None:
        logger.info("learning orchestrator attached to trade hooks")
    else:
        logger.info("learning orchestrator detached from trade hooks")


def get_orchestrator() -> Any:
    return _orchestrator


def is_learning_enabled() -> bool:
    if _LEARNER_DISABLED:
        return False
    return _orchestrator is not None


def notify_entry(
    symbol: str, strategy_id: str, qty: float, price: float
) -> None:
    """Called by _open_position. No-op if learning is disabled."""
    if not is_learning_enabled():
        return
    try:
        _orchestrator.on_trade_entry(symbol, strategy_id, qty, price)
    except Exception as e:
        logger.warning(f"learning notify_entry failed: {e}")


def notify_close(symbol: str, exit_price: float, strategy_id: str = "") -> None:
    """Called by _close_position. No-op if learning is disabled.

    Aggregates by symbol — if multiple positions closed in the same tick for
    the same symbol, we close them with the most recent exit price (the
    orchestrator's per-symbol close logic handles the rest).
    """
    if not is_learning_enabled():
        return
    try:
        _orchestrator.on_trade_close({symbol: exit_price})
    except Exception as e:
        logger.warning(f"learning notify_close failed: {e}")
