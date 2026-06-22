"""JSON API endpoints consumed by the dashboard frontend (Alpine.js)."""

from typing import Any, Dict, List

from fastapi import APIRouter, Query

from src.dashboard.data_service import (
    get_market_data,
    get_overview,
    get_sentiment,
    get_settings,
    get_signals,
    get_strategy_list,
    get_trades,
    update_settings,
)

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/overview")
async def api_overview() -> Dict[str, Any]:
    """Dashboard summary for the overview page."""
    return get_overview()


@router.get("/markets/{symbol}")
async def api_markets(symbol: str, days: int = Query(90, ge=1, le=3650)) -> Dict[str, Any]:
    """OHLCV history and latest quote for *symbol*."""
    return get_market_data(symbol, days=days)


@router.get("/strategies")
async def api_strategies() -> List[Dict[str, Any]]:
    """List all registered strategies with metadata."""
    return get_strategy_list()


@router.get("/signals")
async def api_signals() -> List[Dict[str, Any]]:
    """Active trading signals from all strategies."""
    return get_signals()


@router.get("/trades")
async def api_trades() -> List[Dict[str, Any]]:
    """Paper trade history."""
    return get_trades()


@router.get("/sentiment/{symbol}")
async def api_sentiment(
    symbol: str, hours: int = Query(24, ge=1, le=168)
) -> Dict[str, Any]:
    """Sentiment data and aggregate for *symbol*."""
    return get_sentiment(symbol, hours=hours)


@router.get("/settings")
async def api_settings() -> Dict[str, Any]:
    """Current dashboard settings."""
    return get_settings()


@router.put("/settings")
async def api_update_settings(updates: Dict[str, Any]) -> Dict[str, Any]:
    """Update dashboard settings."""
    return update_settings(updates)
