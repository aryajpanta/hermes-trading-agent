"""HTA-compatible API endpoints — bridges the unified system to the old Node API.

These endpoints exist so existing clients (Discord cron, dashboards, external
scripts) continue to work after the migration. New code should use the
TI-style endpoints in ``src.dashboard.api``.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.automation.scheduler import get_cycles, run_tick
from src.automation.review import get_latest_review, run_review_cycle
from src.automation.optimizer import (
    apply_optimization,
    load_strategy,
    propose_optimization,
    run_optimization_cycle,
    save_strategy,
)
from src.execution.paper import PaperTrader
from src.alerts.monitor import (
    add_alert as alerts_add,
    list_alerts as alerts_list,
    remove_alert as alerts_remove,
    reset_alerts as alerts_reset,
    run_monitor as alerts_run,
)
from src.tradingview.webhook import router as tv_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["unified"])

# Mount the TradingView webhook at /webhook (separate prefix from /api)
webhooks = APIRouter(tags=["webhook"])
webhooks.include_router(tv_router)


# ── Status & portfolio (HTA /api/status, /api/portfolio) ─────


@router.get("/status")
async def api_status() -> Dict[str, Any]:
    """HTA-compatible system status."""
    trader = PaperTrader()
    portfolio = trader.get_portfolio()
    cycles = get_cycles(limit=50)
    last_cycle = cycles[0] if cycles else None

    return {
        "status": "running",
        "portfolio": {
            "cashBalance": portfolio.get("cash", 0),
            "openPositions": portfolio.get("positions_count", 0),
            "totalValue": portfolio.get("total_value", 0),
            "totalTrades": len(trader.get_history() or []),
            "winningTrades": portfolio.get("winning_trades", 0),
            "losingTrades": portfolio.get("losing_trades", 0),
        },
        "system": {
            "totalCycles": len(cycles),
            "lastCycle": last_cycle.get("timestamp") if last_cycle else None,
            "service": "unified-trading-intelligence",
        },
    }


@router.get("/portfolio")
async def api_portfolio() -> Dict[str, Any]:
    """Open positions + cash + P&L (HTA-compatible)."""
    trader = PaperTrader()
    portfolio = trader.get_portfolio()
    positions = []
    for p in trader.portfolio.open_positions:
        pd = p.to_dict()
        positions.append(
            {
                "id": f"{p.symbol}_{p.entry_time.isoformat() if p.entry_time else 'unknown'}",
                "symbol": p.symbol,
                "assetClass": "crypto" if p.symbol in ("BTC", "ETH", "SOL", "DOGE") else "stock",
                "side": "long" if p.direction.value == "LONG" else "short",
                "quantity": p.quantity,
                "entryPrice": p.entry_price,
                "currentPrice": p.entry_price,  # not stored separately; entry is fallback
                "currentValue": p.quantity * p.entry_price,
                "stopLoss": p.stop_loss,
                "takeProfit": p.take_profit,
                "status": p.status.value,
                "reason": p.strategy_id,
                "pnl": p.unrealized_pnl,
                "openedAt": p.entry_time.isoformat() if p.entry_time else None,
                "raw": pd,
            }
        )
    return {
        "balances": {"USD": portfolio.get("cash", 0)},
        "positions": positions,
        "tradeCount": len(trader.get_history() or []),
        "totalValue": portfolio.get("total_value", 0),
        "peakBalance": 100000.0,
    }


@router.get("/trades")
async def api_trades(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """HTA-compatible trade list."""
    trader = PaperTrader()
    history = trader.get_history() or []
    return {
        "total": len(history),
        "returned": min(limit, len(history)),
        "offset": 0,
        "limit": limit,
        "trades": history[:limit],
    }


@router.get("/cycles")
async def api_cycles(limit: int = Query(50, ge=1, le=500)) -> Dict[str, Any]:
    """Automation cycle log."""
    cycles = get_cycles(limit=limit)
    return {"total": len(cycles), "cycles": cycles}


@router.get("/performance")
async def api_performance() -> Dict[str, Any]:
    """Latest review's performance metrics."""
    review = get_latest_review()
    if not review:
        return {"error": "no_review_yet"}
    return review


# ── Manual triggers (HTA /api/tick, /api/review, etc.) ─────


@router.post("/tick")
async def api_tick() -> Dict[str, Any]:
    """Manually trigger a tick."""
    cycle = run_tick(dry_run=False)
    return {"status": "ok", "cycle": cycle}


@router.post("/paper/order")
async def api_paper_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Manually place a paper order."""
    trader = PaperTrader()
    result = trader.execute_signal(payload)
    return {"status": "ok", "position": result}


@router.post("/review")
async def api_review() -> Dict[str, Any]:
    """Manually trigger a review cycle."""
    review = run_review_cycle()
    return {"status": "ok", "review": review}


@router.get("/optimize/propose")
async def api_optimize_propose() -> Dict[str, Any]:
    """Propose a parameter change (does not apply)."""
    review = get_latest_review()
    return propose_optimization(review)


@router.post("/optimize/apply")
async def api_optimize_apply(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a specific parameter change."""
    return apply_optimization(payload)


@router.post("/optimize/cycle")
async def api_optimize_cycle(auto_apply: bool = False) -> Dict[str, Any]:
    """Run a full propose + optional apply cycle."""
    review = get_latest_review()
    return run_optimization_cycle(review=review, auto_apply=auto_apply)


@router.get("/strategy")
async def api_strategy() -> Dict[str, Any]:
    """Current strategy config (HTA-style)."""
    s = load_strategy()
    return s or {"error": "no_strategy"}


@router.post("/strategy/update")
async def api_strategy_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Replace the strategy config."""
    save_strategy(payload)
    return {"status": "ok", "strategy": load_strategy()}


@router.get("/automation/status")
async def api_automation_status() -> Dict[str, Any]:
    """Return the current automation scheduler status (set by main app)."""
    from src.main import get_scheduler_status

    return get_scheduler_status()


# ── Prices + history (HTA /api/prices, /api/history) ───────


@router.get("/prices")
async def api_prices(symbols: str = Query(...)) -> Dict[str, Any]:
    """HTA-compatible prices endpoint."""
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    out: Dict[str, Any] = {}
    for sym in sym_list:
        price = None
        change_24h = None
        # Try Binance for crypto
        try:
            from src.data.sources.binance import BinanceSource

            p = BinanceSource().fetch_price(sym)
            if p:
                price = float(p)
            t = BinanceSource().fetch_24h(sym)
            if t and "priceChangePercent" in t:
                change_24h = float(t["priceChangePercent"]) / 100.0
        except Exception:
            pass
        if price is None:
            try:
                from src.data.sources.coingecko import CoinGeckoSource

                md = CoinGeckoSource().get_market_data(sym)
                if md:
                    price = float(md.get("current_price") or 0) or None
                    change_24h = float(md.get("price_change_24h") or 0) / 100.0 if md.get("price_change_24h") else None
            except Exception:
                pass
        if price is None:
            try:
                import yfinance as yf

                # Try both symbol and SYMBOL-USD (different exchanges)
                for tk in (sym, f"{sym}-USD"):
                    t = yf.Ticker(tk)
                    hist = t.history(period="5d")
                    if not hist.empty:
                        p = float(hist["Close"].iloc[-1])
                        # Sanity check: crypto should be > $100
                        if sym in ("BTC", "ETH", "SOL", "DOGE", "BNB", "XRP") and p < 100:
                            continue
                        price = p
                        if len(hist) >= 2:
                            prev = float(hist["Close"].iloc[-2])
                            change_24h = (price - prev) / prev if prev else None
                        break
            except Exception:
                pass
        asset_class = "crypto" if sym in ("BTC", "ETH", "SOL", "DOGE", "BNB", "XRP") else "stock"
        out[sym] = {
            "price": price,
            "change24h": change_24h,
            "assetClass": asset_class,
        }
    return out


@router.get("/history")
async def api_history(
    symbol: str = Query(...),
    days: int = Query(90, ge=1, le=3650),
    interval: str = Query("1d"),
) -> Dict[str, Any]:
    """HTA-compatible history endpoint."""
    try:
        from src.data.collector import MarketDataCollector

        collector = MarketDataCollector()
        history = collector.get_history(symbol, days=days)
        if history is None or history.empty:
            return {"symbol": symbol, "candles": []}
        candles = []
        for _, row in history.iterrows():
            candles.append(
                {
                    "time": int(row.name.timestamp() * 1000)
                    if hasattr(row.name, "timestamp")
                    else None,
                    "open": float(row.get("Open", 0)),
                    "high": float(row.get("High", 0)),
                    "low": float(row.get("Low", 0)),
                    "close": float(row.get("Close", 0)),
                    "volume": float(row.get("Volume", 0)),
                }
            )
        return {"symbol": symbol, "candles": candles}
    except Exception as e:
        return {"symbol": symbol, "candles": [], "error": str(e)}


# ── Alerts (HTA /api/alerts) ───────────────────────────────


@router.get("/alerts")
async def api_alerts_list() -> List[Dict[str, Any]]:
    return alerts_list()


@router.post("/alerts")
async def api_alerts_create(payload: Dict[str, Any]) -> Dict[str, Any]:
    return alerts_add(
        symbol=payload.get("symbol", "").upper(),
        asset_class=payload.get("assetClass", "crypto"),
        condition=payload.get("condition", "gte"),
        value=float(payload.get("value", 0)),
        action=payload.get("action", "alert"),
        message=payload.get("message", ""),
        repeatable=bool(payload.get("repeatable", False)),
    )


@router.delete("/alerts/{alert_id}")
async def api_alerts_delete(alert_id: str) -> Dict[str, Any]:
    ok = alerts_remove(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail="not found")
    return {"status": "ok"}


@router.post("/alerts/run")
async def api_alerts_run() -> Dict[str, Any]:
    return alerts_run()


@router.post("/alerts/reset")
async def api_alerts_reset() -> Dict[str, Any]:
    n = alerts_reset()
    return {"status": "ok", "reset_count": n}


# ── Alpaca proxy (HTA /api/alpaca/*) ───────────────────────


@router.get("/alpaca/status")
async def api_alpaca_status() -> Dict[str, Any]:
    from src.broker.alpaca import BrokerConnection

    return BrokerConnection.instance().status()


@router.get("/alpaca/account")
async def api_alpaca_account() -> Dict[str, Any]:
    from src.broker.alpaca import BrokerConnection

    bc = BrokerConnection.instance()
    if not bc.broker.connected:
        try:
            bc.connect()
        except Exception as e:
            raise HTTPException(status_code=503, detail=f"connect_failed: {e}")
    acc = bc.get_account()
    if not acc:
        raise HTTPException(status_code=503, detail="no_account")
    return acc


@router.get("/alpaca/positions")
async def api_alpaca_positions() -> List[Dict[str, Any]]:
    from src.broker.alpaca import BrokerConnection

    bc = BrokerConnection.instance()
    if not bc.broker.connected:
        bc.connect()
    return bc.get_positions()


@router.get("/alpaca/orders")
async def api_alpaca_orders(status: Optional[str] = None) -> List[Dict[str, Any]]:
    from src.broker.alpaca import BrokerConnection

    bc = BrokerConnection.instance()
    if not bc.broker.connected:
        bc.connect()
    return bc.get_orders(status=status)


@router.post("/alpaca/connect")
async def api_alpaca_connect() -> Dict[str, Any]:
    from src.broker.alpaca import BrokerConnection

    return BrokerConnection.instance().connect()


@router.post("/alpaca/disconnect")
async def api_alpaca_disconnect() -> Dict[str, Any]:
    from src.broker.alpaca import BrokerConnection

    return BrokerConnection.instance().disconnect()


@router.post("/alpaca/sync")
async def api_alpaca_sync() -> Dict[str, Any]:
    from src.broker.alpaca import BrokerConnection

    return BrokerConnection.instance().sync_portfolio()


# ── Sentiment ──────────────────────────────────────────────


@router.get("/sentiment/{symbol}")
async def api_sentiment(symbol: str) -> Dict[str, Any]:
    """Per-symbol sentiment (Gemini AI if configured)."""
    from src.sentiment.gemini import GeminiSentiment

    g = GeminiSentiment()
    if not g.is_configured:
        return {
            "symbol": symbol.upper(),
            "sentimentScore": 0.0,
            "confidence": 0.0,
            "reason": "GEMINI_API_KEY not configured",
        }
    return {"symbol": symbol.upper(), **g.fetch_sentiment(symbol)}
