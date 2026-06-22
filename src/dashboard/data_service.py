"""Data service layer — thin wrapper that the dashboard reads from.

All functions are safe to call even when databases are empty; they return
empty / zero-valued structures rather than raising.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy singletons — created on first access
# ---------------------------------------------------------------------------
_collector: Optional[Any] = None
_sentiment_storage: Optional[Any] = None


def _get_market_collector() -> Any:
    """Return a MarketDataCollector (created once, reused)."""
    global _collector  # noqa: PLW0603
    if _collector is None:
        from src.data.collector import MarketDataCollector

        _collector = MarketDataCollector(
            storage_path="data/market.db",
            yahoo_enabled=True,
            coingecko_enabled=False,
            alphavantage_enabled=False,
        )
    return _collector


def _get_sentiment_storage() -> Any:
    """Return a SentimentStorage (created once, reused)."""
    global _sentiment_storage  # noqa: PLW0603
    if _sentiment_storage is None:
        from src.data.sentiment.collector import SentimentStorage

        _sentiment_storage = SentimentStorage(db_path="data/sentiment.db")
    return _sentiment_storage


# ---------------------------------------------------------------------------
# Market data helpers
# ---------------------------------------------------------------------------

KEY_SYMBOLS = ["SPY", "QQQ", "BTC", "ETH", "GC=F", "EUR-USD"]


def get_overview() -> Dict[str, Any]:
    """Build the dashboard overview dict."""
    collector = _get_market_collector()
    market_summary: List[Dict[str, Any]] = []
    for sym in KEY_SYMBOLS:
        latest = collector.get_latest(sym)
        if latest is not None:
            market_summary.append(
                {
                    "symbol": sym,
                    "close": latest.close,
                    "timestamp": latest.timestamp.isoformat(),
                }
            )

    symbols = collector.list_symbols(active_only=True)

    return {
        "market_summary": market_summary,
        "tracked_symbols": len(symbols),
        "active_strategies": _get_active_strategy_count(),
        "active_signals": _get_active_signals_summary(),
        "recent_trades": _get_recent_trades(limit=10),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def get_market_data(symbol: str, days: int = 90) -> Dict[str, Any]:
    """Return OHLCV history for *symbol*."""
    collector = _get_market_collector()
    df: pd.DataFrame = collector.get_history(symbol, days=days)
    latest = collector.get_latest(symbol)

    if df.empty:
        return {
            "symbol": symbol,
            "history": [],
            "latest": None,
        }

    # Convert to list-of-dicts for JSON serialisation
    df["timestamp"] = df["timestamp"].astype(str)
    history = df.to_dict(orient="records")

    latest_dict: Optional[Dict[str, Any]] = None
    if latest is not None:
        latest_dict = {
            "symbol": latest.symbol,
            "close": latest.close,
            "open": latest.open,
            "high": latest.high,
            "low": latest.low,
            "volume": latest.volume,
            "timestamp": latest.timestamp.isoformat(),
        }

    return {
        "symbol": symbol,
        "history": history,
        "latest": latest_dict,
    }


# ---------------------------------------------------------------------------
# Strategy helpers
# ---------------------------------------------------------------------------

def get_strategy_list() -> List[Dict[str, Any]]:
    """List all registered strategies with metadata."""
    try:
        from src.strategy.library import list_strategies

        strategies = list_strategies()
        return [
            {
                "id": s.id,
                "name": s.name,
                "category": s.category,
                "description": s.description,
                "timeframes": s.timeframes,
                "assets": s.assets,
            }
            for s in strategies
        ]
    except Exception as exc:
        logger.warning("Could not load strategies: %s", exc)
        return []


def _get_active_strategy_count() -> int:
    return len(get_strategy_list())


def get_signals() -> List[Dict[str, Any]]:
    """Evaluate all strategies on available data and return current signals."""
    try:
        from src.strategy.library import evaluate, list_strategies

        strategies = list_strategies()
        signals: List[Dict[str, Any]] = []
        collector = _get_market_collector()

        for strat in strategies:
            # Try first asset in strategy's asset list, fallback to SPY
            symbol = strat.assets[0] if strat.assets else "SPY"
            df: pd.DataFrame = collector.get_history(symbol, days=90)
            if df.empty:
                continue
            # Ensure proper columns
            df = df.set_index("timestamp") if "timestamp" in df.columns and df.index.name != "timestamp" else df
            if len(df) < 5:
                continue
            try:
                sig = evaluate(strat.id, df, symbol=symbol)
                signals.append(
                    {
                        "strategy_id": sig.strategy_id,
                        "symbol": sig.symbol,
                        "direction": sig.direction,
                        "confidence": sig.confidence,
                        "reasoning": sig.reasoning,
                        "timestamp": sig.timestamp.isoformat(),
                    }
                )
            except Exception as exc:
                logger.debug("Eval %s failed: %s", strat.id, exc)
        return signals
    except Exception as exc:
        logger.warning("Could not generate signals: %s", exc)
        return []


def _get_active_signals_summary() -> Dict[str, Any]:
    """Quick summary of signals for the overview page."""
    signals = get_signals()
    buy_count = sum(1 for s in signals if s["direction"] > 0.3)
    sell_count = sum(1 for s in signals if s["direction"] < -0.3)
    neutral_count = len(signals) - buy_count - sell_count
    return {
        "total": len(signals),
        "buy": buy_count,
        "sell": sell_count,
        "neutral": neutral_count,
    }


# ---------------------------------------------------------------------------
# Trades (paper trading)
# ---------------------------------------------------------------------------
# For now, we expose an empty list; a real paper-trading engine would persist
# trades to a database.  This placeholder keeps the dashboard functional.

_TRADES: List[Dict[str, Any]] = []


def get_trades() -> List[Dict[str, Any]]:
    """Return paper trade history."""
    return list(_TRADES)


def _get_recent_trades(limit: int = 10) -> List[Dict[str, Any]]:
    return get_trades()[-limit:]


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------

def get_sentiment(symbol: str, hours: int = 24) -> Dict[str, Any]:
    """Return sentiment data for *symbol*."""
    storage = _get_sentiment_storage()
    try:
        aggregate = storage.get_aggregate(symbol, hours=hours)
        signals_raw = storage.get_signals(symbol, hours=hours)
        signals = [
            {
                "source": s.source.value,
                "headline": s.headline,
                "sentiment_score": s.sentiment_score,
                "confidence": s.confidence,
                "url": s.url,
                "timestamp": s.timestamp.isoformat(),
            }
            for s in signals_raw
        ]
        return {
            "symbol": symbol,
            "aggregate": {
                "mean_score": aggregate.mean_score,
                "signal_count": aggregate.signal_count,
                "bullish_count": aggregate.bullish_count,
                "bearish_count": aggregate.bearish_count,
                "neutral_count": aggregate.neutral_count,
                "confidence": aggregate.confidence,
                "label": aggregate.sentiment_label,
            },
            "signals": signals,
        }
    except Exception as exc:
        logger.warning("Sentiment query failed for %s: %s", symbol, exc)
        return {
            "symbol": symbol,
            "aggregate": {
                "mean_score": 0.0,
                "signal_count": 0,
                "bullish_count": 0,
                "bearish_count": 0,
                "neutral_count": 0,
                "confidence": 0.0,
                "label": "NEUTRAL",
            },
            "signals": [],
        }


# ---------------------------------------------------------------------------
# Settings (placeholder)
# ---------------------------------------------------------------------------

_SETTINGS: Dict[str, Any] = {
    "auto_refresh_seconds": 60,
    "dark_mode": True,
    "watchlist": KEY_SYMBOLS,
    "api_keys": {},
    "alert_thresholds": {
        "sentiment_extreme": 0.5,
        "drawdown_warning": 0.10,
    },
}


def get_settings() -> Dict[str, Any]:
    return dict(_SETTINGS)


def update_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    _SETTINGS.update(updates)
    return get_settings()
