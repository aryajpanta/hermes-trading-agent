"""TradingView webhook receiver — FastAPI router.

Ported from hermes-trading-agent (HTA). Receives JSON alerts from
TradingView, validates the optional shared secret, persists them,
and (optionally) routes ``action: buy/sell`` alerts into the
paper trader.

Expected payload (TradingView alert message JSON):
    {
        "secret": "<shared secret if WEBHOOK_SECRET set>",
        "symbol": "BTCUSDT",
        "assetClass": "crypto" | "stock" | "forex",
        "action": "buy" | "sell" | "alert" | "close",
        "price": 50000,
        "qty": 0.1,
        "strategy": "rsi_oversold",
        "message": "Optional text from TradingView"
    }
"""

import hashlib
import hmac
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["tradingview"])

WEBHOOK_LOG_PATH = Path("data/webhook_alerts.json")
WEBHOOK_ERRORS_PATH = Path("data/webhook_errors.json")


# ── Persistence helpers ──────────────────────────────────────


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _append(path: Path, record: Dict[str, Any]) -> None:
    arr = _load_json(path, [])
    arr.append(record)
    # Keep last 500 entries
    arr = arr[-500:]
    _save_json(path, arr)


# ── Payload normalization ─────────────────────────────────────


def _normalize(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a TradingView payload into our internal alert format."""
    return {
        "symbol": (payload.get("symbol") or "").upper(),
        "asset_class": (payload.get("assetClass") or "crypto").lower(),
        "action": (payload.get("action") or payload.get("signal") or "").lower(),
        "price": float(payload.get("price") or payload.get("close") or 0),
        "qty": float(payload.get("qty") or payload.get("quantity") or 0),
        "strategy": payload.get("strategy") or payload.get("strategy_name") or "default",
        "message": payload.get("message") or payload.get("alert_message") or "",
        "interval": payload.get("interval") or payload.get("timeframe") or "",
        "received_at": datetime.utcnow().isoformat() + "Z",
        "raw": payload,
    }


# ── Signature verification ────────────────────────────────────


def _verify_signature(secret: str, body: bytes, signature: Optional[str]) -> bool:
    """HMAC-SHA256 verification (TradingView supports custom headers)."""
    if not secret or not signature:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ── Endpoints ────────────────────────────────────────────────


@router.post("/tradingview")
async def receive_tradingview(request: Request) -> Dict[str, Any]:
    """Receive a TradingView alert."""
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception as e:
        _append(WEBHOOK_ERRORS_PATH, {"error": "invalid_json", "detail": str(e)})
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Secret validation — if WEBHOOK_SECRET env is set, require it in body
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "")
    if webhook_secret:
        provided = payload.get("secret") or payload.get("webhookSecret") or ""
        if not hmac.compare_digest(provided, webhook_secret):
            # Try HMAC header
            sig = request.headers.get("X-Webhook-Signature") or request.headers.get(
                "X-TradingView-Signature"
            )
            if not _verify_signature(webhook_secret, body, sig):
                _append(
                    WEBHOOK_ERRORS_PATH,
                    {
                        "error": "invalid_secret",
                        "received_at": datetime.utcnow().isoformat() + "Z",
                    },
                )
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

    alert = _normalize(payload)

    if not alert["symbol"]:
        _append(WEBHOOK_ERRORS_PATH, {"error": "missing_symbol", "raw": payload})
        raise HTTPException(status_code=400, detail="Missing symbol")

    if alert["action"] not in ("buy", "sell", "alert", "close"):
        _append(WEBHOOK_ERRORS_PATH, {"error": "invalid_action", "raw": payload})
        raise HTTPException(status_code=400, detail=f"Invalid action: {alert['action']}")

    # Persist
    _append(WEBHOOK_LOG_PATH, alert)

    # Route actionable alerts to paper trader
    if alert["action"] in ("buy", "sell", "close"):
        try:
            await _route_to_paper(alert)
        except Exception as e:
            logger.error(f"Webhook route-to-paper failed: {e}")
            alert["routing_error"] = str(e)

    return {
        "received": True,
        "alert": {
            "symbol": alert["symbol"],
            "action": alert["action"],
            "price": alert["price"],
            "strategy": alert["strategy"],
        },
    }


async def _route_to_paper(alert: Dict[str, Any]) -> None:
    """Forward a buy/sell/close alert to the paper trader.

    Imports are inside the function to avoid circular imports at startup.
    """
    from src.execution.paper import PaperTrader

    trader = PaperTrader()
    if alert["action"] == "buy":
        trader.execute_signal(
            {
                "symbol": alert["symbol"],
                "direction": "BUY",
                "confidence": 0.7,
                "reasoning": f"TradingView webhook: {alert['message'][:100]}",
            }
        )
    elif alert["action"] == "sell":
        trader.execute_signal(
            {
                "symbol": alert["symbol"],
                "direction": "SELL",
                "confidence": 0.7,
                "reasoning": f"TradingView webhook: {alert['message'][:100]}",
            }
        )
    elif alert["action"] == "close":
        # Close any open position for this symbol
        for pos in list(trader.portfolio.positions):
            if pos.symbol == alert["symbol"]:
                trader.close_position(pos, alert["price"] or 0, "webhook")


# ── Setup guide ──────────────────────────────────────────────


@router.get("/../api/tradingview/setup", include_in_schema=False)
async def setup_guide() -> Dict[str, Any]:
    """Documentation endpoint for setting up TradingView alerts."""
    # FastAPI doesn't allow `..` paths, so mount separately in main
    return {
        "url": "<your-service-url>/webhook/tradingview",
        "method": "POST",
        "content_type": "application/json",
        "secret_env": "WEBHOOK_SECRET (set on Railway)",
        "example_payload": {
            "secret": "<your-shared-secret>",
            "symbol": "BTCUSDT",
            "assetClass": "crypto",
            "action": "buy",
            "price": "{{close}}",
            "qty": 0.01,
            "strategy": "rsi_oversold",
            "message": "Alert from TradingView: {{time}}",
        },
        "tradingview_setup_steps": [
            "1. Open TradingView, click Alerts → Create Alert",
            "2. Set condition (indicator crossing, price level, etc.)",
            "3. In 'Webhook URL', paste your service URL + /webhook/tradingview",
            "4. In 'Message', paste the example JSON above (customize as needed)",
            "5. Click Create — alerts will fire on every trigger",
        ],
    }
