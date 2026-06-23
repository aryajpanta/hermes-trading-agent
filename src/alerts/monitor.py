"""Alerts engine — condition-based price alerts.

Ported from hermes-trading-agent (HTA). Persists alert rules in
``data/alerts.json`` and evaluates them on a schedule (every
``AUTOMATION_INTERVAL_MS`` ms by default).

Alert shape:
    {
        "id": "alert_abc123",
        "symbol": "BTC",
        "assetClass": "crypto" | "stock" | "forex",
        "condition": "gte" | "lte" | "cross_above" | "cross_below",
        "value": 75000.0,
        "action": "buy" | "sell" | "alert",
        "message": "...",
        "repeatable": false,
        "triggered": false,
        "lastTriggeredAt": null
    }
"""

import logging
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.alerts.store import AlertStore

logger = logging.getLogger(__name__)


# Track last seen price per (alert_id) to detect crossings
_PRICE_HISTORY: Dict[str, float] = {}
_HISTORY_LOCK = threading.Lock()


# ── Condition evaluation ────────────────────────────────────


def _check_condition(
    current: float, condition: str, threshold: float, previous: Optional[float]
) -> bool:
    if condition == "gte":
        return current >= threshold
    if condition == "lte":
        return current <= threshold
    if condition == "cross_above":
        return previous is not None and previous < threshold <= current
    if condition == "cross_below":
        return previous is not None and previous > threshold >= current
    return False


# ── Price fetching ──────────────────────────────────────────


def _fetch_price(symbol: str, asset_class: str) -> Optional[float]:
    """Try multiple sources in priority order: Binance → CoinGecko → Yahoo."""
    asset_class = (asset_class or "crypto").lower()

    # Try Binance for crypto
    if asset_class == "crypto":
        try:
            from src.data.sources.binance import BinanceSource

            p = BinanceSource().fetch_price(symbol)
            if p:
                return p
        except Exception as e:
            logger.debug(f"Binance fetch failed for {symbol}: {e}")

        # Fallback: CoinGecko
        try:
            from src.data.sources.coingecko import CoinGeckoSource

            src = CoinGeckoSource()
            md = src.get_market_data(symbol)
            if md and md.get("current_price"):
                return float(md["current_price"])
        except Exception as e:
            logger.debug(f"CoinGecko fetch failed for {symbol}: {e}")

    # Yahoo Finance fallback (works for stocks, ETFs, and some crypto pairs)
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.debug(f"Yahoo fetch failed for {symbol}: {e}")

    return None


# ── Public API ──────────────────────────────────────────────


def add_alert(
    symbol: str,
    asset_class: str,
    condition: str,
    value: float,
    action: str = "alert",
    message: str = "",
    repeatable: bool = False,
) -> Dict[str, Any]:
    """Add a new alert rule."""
    store = AlertStore()
    return store.add(
        symbol=symbol,
        asset_class=asset_class,
        condition=condition,
        value=value,
        action=action,
        message=message,
        repeatable=repeatable,
    )


def list_alerts() -> List[Dict[str, Any]]:
    return AlertStore().list()


def remove_alert(alert_id: str) -> bool:
    ok = AlertStore().remove(alert_id)
    with _HISTORY_LOCK:
        _PRICE_HISTORY.pop(alert_id, None)
    return ok


def reset_alerts() -> int:
    return AlertStore().reset_all()


def run_monitor() -> Dict[str, Any]:
    """Evaluate every alert; execute actions on triggered ones.

    Returns a summary dict with counts and triggered alert list.
    """
    store = AlertStore()
    alerts = store.list()
    triggered: List[Dict[str, Any]] = []

    for alert in alerts:
        # Skip one-shot alerts already triggered (unless repeatable)
        if alert.get("triggered") and not alert.get("repeatable"):
            continue

        price = _fetch_price(alert["symbol"], alert.get("assetClass", "crypto"))
        if price is None:
            continue

        with _HISTORY_LOCK:
            previous = _PRICE_HISTORY.get(alert["id"])
            _PRICE_HISTORY[alert["id"]] = price

        if _check_condition(price, alert["condition"], alert["value"], previous):
            result = _execute_action(alert, price)
            triggered.append(
                {
                    "id": alert["id"],
                    "symbol": alert["symbol"],
                    "condition": alert["condition"],
                    "value": alert["value"],
                    "currentPrice": price,
                    "action": alert["action"],
                    "executed": result,
                }
            )
            store.mark_triggered(alert["id"])

    return {
        "checked": len(alerts),
        "triggered": triggered,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _execute_action(alert: Dict[str, Any], price: float) -> Dict[str, Any]:
    """Execute the alert's action. For 'buy'/'sell' we route to PaperTrader."""
    action = alert.get("action", "alert")
    if action not in ("buy", "sell"):
        return {"executed": False, "reason": f"action={action} (notify-only)"}

    try:
        from src.execution.paper import PaperTrader

        trader = PaperTrader()
        result = trader.execute_signal(
            {
                "symbol": alert["symbol"],
                "direction": "BUY" if action == "buy" else "SELL",
                "confidence": 0.7,
                "reasoning": f"Alert {alert['id']}: {alert['message'] or alert['condition'] + ' ' + str(alert['value'])} @ ${price:.4f}",
            }
        )
        return {"executed": bool(result), "price": price}
    except Exception as e:
        logger.error(f"Alert action execution failed: {e}")
        return {"executed": False, "error": str(e)}
