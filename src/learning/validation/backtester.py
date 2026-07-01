"""Lightweight 30-day backtest for a given weight scheme.

Reuses the existing backtesting engine in src.backtest if available;
falls back to a simple equity-curve computation otherwise.
"""
from __future__ import annotations
import logging
import math
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def compute_sharpe(equity_curve: List[float]) -> float:
    """Annualized Sharpe from an equity curve (oldest first)."""
    if len(equity_curve) < 2:
        return 0.0
    rets = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]
        if prev > 0:
            rets.append((equity_curve[i] - prev) / prev)
    if not rets:
        return 0.0
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(1, len(rets) - 1)
    sd = math.sqrt(var) if var > 0 else 1e-9
    return float((mean / sd) * math.sqrt(252))


def backtest_weights(
    weights: Dict[str, float],
    days: int = 30,
    watchlist: Optional[List[str]] = None,
    trades: Optional[List[Dict]] = None,
) -> float:
    """Run a backtest with the given strategy weights and return Sharpe.

    Three modes (in priority order):
    1. If `trades` is provided, use it directly (the "trade replay" mode —
       most reliable for validating that the live model produces good
       weights, since it uses the actual closed trades we have on hand).
    2. If a real backtester exists at src.backtest.engine, call it.
       (Currently no such module — src.strategy.backtester.Backtester exists
       but takes a single strategy, not weights. Future enhancement.)
    3. Fall back to 0.0 (gate treats this as no-improvement).

    Args:
        weights: {strategy_id: weight} — currently not used to filter trades;
            included for forward compatibility with the real backtester
        days: ignored in trade-replay mode (uses whatever is provided)
        watchlist: symbols to include
        trades: list of trade dicts with 'pnl', 'strategy_id', 'symbol' keys
    """
    # Mode 1: trade replay
    if trades:
        return _sharpe_from_trades(trades, weights, watchlist)

    # Mode 2: real backtester (forward-compat hook)
    try:
        from src.backtest.engine import run_backtest
        result = run_backtest(weights=weights, days=days, watchlist=watchlist or [])
        return float(result.get("sharpe", 0.0))
    except ImportError:
        # src.backtest doesn't exist yet; this is expected.
        pass
    except Exception as e:
        logger.warning("backtest_weights: no real backtester, no trades: %s", e)
    return 0.0


def _sharpe_from_trades(
    trades: List[Dict],
    weights: Optional[Dict[str, float]] = None,
    watchlist: Optional[List[str]] = None,
) -> float:
    """Compute Sharpe from a list of trade dicts.

    Each trade: {'pnl': float, 'strategy_id': str, 'symbol': str}.

    If weights provided, weight the per-trade PnL by strategy weight.
    Build a synthetic equity curve by sorting trades by exit_ts and
    accumulating weighted PnL.
    """
    if not trades:
        return 0.0
    # Filter by watchlist if provided
    if watchlist:
        wl = set(watchlist)
        trades = [t for t in trades if t.get("symbol") in wl]
    # Sort by time if available
    sorted_trades = sorted(
        trades, key=lambda t: t.get("exit_ts") or t.get("ts") or ""
    )
    # Build equity curve
    equity = [1.0]
    for t in sorted_trades:
        pnl = float(t.get("pnl", 0.0))
        sid = t.get("strategy_id", "")
        w = (weights or {}).get(sid, 1.0) if weights else 1.0
        # PnL is a percentage; equity grows by weighted_pnl
        equity.append(equity[-1] * (1.0 + pnl * w))
    return compute_sharpe(equity)
