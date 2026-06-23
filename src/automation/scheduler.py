"""Continuous automation scheduler — async background tasks.

Ported from hermes-trading-agent (HTA) to Python. Runs the trading
loop as an asyncio background task inside the FastAPI app process.

Two loops:
  - **tick loop** (default 60s): fetch prices, update positions,
    check stop-loss/take-profit, evaluate alerts
  - **review loop** (default 24h): performance review + parameter
    optimizer (see review.py and optimizer.py)

Disable with ``ENABLE_AUTOMATION=false``.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.execution.paper import PaperTrader

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_MONITOR_INTERVAL_S = 60.0
DEFAULT_REVIEW_INTERVAL_S = 86_400.0  # 24h

CYCLE_LOG_PATH = Path("data/cycles.json")


# ── Cycle log ───────────────────────────────────────────────


def _load_cycles() -> List[Dict[str, Any]]:
    if not CYCLE_LOG_PATH.exists():
        return []
    try:
        with open(CYCLE_LOG_PATH) as f:
            return json.load(f)
    except Exception:
        return []


def _append_cycle(entry: Dict[str, Any], max_keep: int = 500) -> None:
    arr = _load_cycles()
    arr.append(entry)
    arr = arr[-max_keep:]
    CYCLE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CYCLE_LOG_PATH, "w") as f:
        json.dump(arr, f, indent=2, default=str)


def get_cycles(limit: int = 50) -> List[Dict[str, Any]]:
    arr = _load_cycles()
    return arr[-limit:][::-1]  # newest first


# ── Tick logic (sync, called from async wrapper) ─────────────


def run_tick(
    watchlist: Optional[List[str]] = None, dry_run: bool = False
) -> Dict[str, Any]:
    """One trading loop iteration.

    1. Fetch prices for the watchlist
    2. Update paper portfolio with current prices
    3. Check stop-loss / take-profit; auto-close breached positions
    4. Run the alert monitor
    5. Append a cycle log entry
    """
    started = time.time()
    wl = watchlist or ["BTC", "ETH", "SOL", "AAPL", "QQQ", "SPY"]

    # 1. Fetch prices
    prices: Dict[str, float] = {}
    for sym in wl:
        try:
            from src.data.sources.binance import BinanceSource

            p = BinanceSource().fetch_price(sym)
            if p:
                prices[sym] = float(p)
                continue
        except Exception:
            pass
        # Fallback: yfinance (works for stocks, ETFs, and crypto with -USD suffix)
        try:
            import yfinance as yf

            # Try both symbol and SYMBOL-USD
            for tk in (sym, f"{sym}-USD"):
                t = yf.Ticker(tk)
                hist = t.history(period="5d")
                if not hist.empty and float(hist["Close"].iloc[-1]) > 100:
                    prices[sym] = float(hist["Close"].iloc[-1])
                    break
        except Exception:
            pass

    # 2. Update paper positions
    trader = PaperTrader()
    if prices:
        trader.update_positions(prices)
        # Persist so /api/portfolio reflects the latest unrealized P&L
        try:
            trader.save_to_disk()
        except Exception as e:
            logger.debug(f"save_to_disk skipped: {e}")

    # 3. Auto-close SL/TP breaches
    closed: List[Dict[str, Any]] = []
    if prices:
        try:
            for pos in list(trader.portfolio.positions):
                if pos.status.value != "open":
                    continue
                price = prices.get(pos.symbol)
                if price is None:
                    continue
                # Find stop_loss / take_profit (Position has them as direct fields)
                sl = getattr(pos, "stop_loss", None)
                tp = getattr(pos, "take_profit", None)
                if sl and price <= sl:
                    trader._close_position(pos, price, "stop_loss")
                    closed.append({"symbol": pos.symbol, "reason": "stop_loss", "price": price})
                elif tp and price >= tp:
                    trader._close_position(pos, price, "take_profit")
                    closed.append({"symbol": pos.symbol, "reason": "take_profit", "price": price})
        except Exception as e:
            logger.error(f"SL/TP check failed: {e}")

    # 4. Run alerts
    alerts_result: Dict[str, Any] = {"checked": 0, "triggered": []}
    try:
        from src.alerts.monitor import run_monitor

        alerts_result = run_monitor()
    except Exception as e:
        logger.error(f"Alert monitor failed: {e}")

    # 5. Cycle log
    duration = time.time() - started
    cycle = {
        "type": "tick",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "duration_s": round(duration, 3),
        "prices": prices,
        "closed_positions": closed,
        "alerts_checked": alerts_result.get("checked", 0),
        "alerts_triggered": len(alerts_result.get("triggered", [])),
        "open_positions": sum(
            1
            for p in trader.portfolio.positions
            if str(p.status.value).lower() == "open"
        ),
    }
    if not dry_run:
        _append_cycle(cycle)

    return cycle


# ── Async loop ──────────────────────────────────────────────


class AutomationScheduler:
    """Long-running background scheduler.

    Started in FastAPI lifespan; stopped on shutdown. Each loop is
    guarded against overlap (won't run if previous is still running).
    """

    def __init__(
        self,
        monitor_interval_s: float = DEFAULT_MONITOR_INTERVAL_S,
        review_interval_s: float = DEFAULT_REVIEW_INTERVAL_S,
        enabled: bool = True,
        watchlist: Optional[List[str]] = None,
    ) -> None:
        self.monitor_interval_s = float(
            os.environ.get(
                "AUTOMATION_INTERVAL_MS", str(monitor_interval_s * 1000)
            )
        ) / 1000.0
        self.review_interval_s = float(
            os.environ.get(
                "REVIEW_INTERVAL_MS", str(review_interval_s * 1000)
            )
        ) / 1000.0
        self.enabled = (
            os.environ.get("ENABLE_AUTOMATION", "true" if enabled else "false").lower()
            not in ("false", "0", "no", "off")
        )
        self.watchlist = watchlist
        self._monitor_task: Optional[asyncio.Task] = None
        self._review_task: Optional[asyncio.Task] = None
        self._running = False
        self._monitor_running = False
        self._review_running = False
        self._status: Dict[str, Any] = {
            "enabled": self.enabled,
            "monitor_interval_s": self.monitor_interval_s,
            "review_interval_s": self.review_interval_s,
            "monitor": {"runs": 0, "last_run": None, "last_error": None},
            "review": {"runs": 0, "last_run": None, "last_error": None},
        }

    @property
    def status(self) -> Dict[str, Any]:
        return self._status

    async def start(self) -> None:
        if not self.enabled:
            logger.info("[Automation] disabled (ENABLE_AUTOMATION=false)")
            return
        if self._running:
            return
        self._running = True
        # Stagger first run by 5s to let the server settle
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        self._review_task = asyncio.create_task(self._review_loop())
        logger.info(
            f"[Automation] started — monitor every {self.monitor_interval_s}s, "
            f"review every {self.review_interval_s}s"
        )

    async def stop(self) -> None:
        self._running = False
        for task in (self._monitor_task, self._review_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        self._monitor_task = self._review_task = None
        logger.info("[Automation] stopped")

    async def _monitor_loop(self) -> None:
        # First run after a small delay
        await asyncio.sleep(5.0)
        while self._running:
            if not self._monitor_running:
                self._monitor_running = True
                try:
                    result = await asyncio.to_thread(
                        run_tick, self.watchlist, False
                    )
                    self._status["monitor"]["last_run"] = result["timestamp"]
                    self._status["monitor"]["runs"] += 1
                    self._status["monitor"]["last_error"] = None
                    if result.get("closed_positions"):
                        logger.info(
                            f"[Automation] auto-closed "
                            f"{len(result['closed_positions'])} positions"
                        )
                except Exception as e:
                    self._status["monitor"]["last_error"] = str(e)
                    logger.error(f"[Automation] monitor error: {e}")
                finally:
                    self._monitor_running = False
            await asyncio.sleep(self.monitor_interval_s)

    async def _review_loop(self) -> None:
        # Stagger review so it doesn't run at the same time as monitor
        await asyncio.sleep(self.review_interval_s)
        while self._running:
            if not self._review_running:
                self._review_running = True
                try:
                    from src.automation.review import run_review_cycle

                    result = await asyncio.to_thread(run_review_cycle)
                    self._status["review"]["last_run"] = (
                        result.get("timestamp") if isinstance(result, dict) else None
                    )
                    self._status["review"]["runs"] += 1
                    self._status["review"]["last_error"] = None
                except Exception as e:
                    self._status["review"]["last_error"] = str(e)
                    logger.error(f"[Automation] review error: {e}")
                finally:
                    self._review_running = False
            await asyncio.sleep(self.review_interval_s)
