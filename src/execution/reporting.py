"""Reporting for paper trading performance."""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.execution.position import Position, PositionStatus


def daily_pnl_summary(positions: List[Position], target_date: Optional[datetime] = None) -> Dict[str, Any]:
    """Summarize daily P&L from trades closed on a given day.

    Args:
        positions: All positions (open + closed).
        target_date: Date to summarize (default: today, date-only comparison).

    Returns:
        Dictionary with daily summary.
    """
    if target_date is None:
        target_date = datetime.utcnow()

    closed_today = [
        p for p in positions
        if p.status == PositionStatus.CLOSED
        and p.exit_time.date() == target_date.date()
    ]

    total_pnl = sum(p.realized_pnl for p in closed_today)
    wins = [p for p in closed_today if p.realized_pnl > 0]
    losses = [p for p in closed_today if p.realized_pnl <= 0]

    return {
        "date": target_date.date().isoformat(),
        "trades_closed": len(closed_today),
        "total_pnl": total_pnl,
        "wins": len(wins),
        "losses": len(losses),
        "win_pnl": sum(p.realized_pnl for p in wins),
        "loss_pnl": sum(p.realized_pnl for p in losses),
    }


def weekly_performance(positions: List[Position], week_start: Optional[datetime] = None) -> Dict[str, Any]:
    """Performance summary for a calendar week.

    Args:
        positions: All positions.
        week_start: Start of the week (default: 7 days ago).

    Returns:
        Weekly performance dictionary.
    """
    if week_start is None:
        now = datetime.utcnow()
        week_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = week_start.replace(day=max(1, week_start.day - 6))

    closed_this_week = [
        p for p in positions
        if p.status == PositionStatus.CLOSED
        and p.exit_time >= week_start
    ]

    total_pnl = sum(p.realized_pnl for p in closed_this_week)
    wins = sum(1 for p in closed_this_week if p.realized_pnl > 0)
    total = len(closed_this_week)

    return {
        "week_start": week_start.date().isoformat(),
        "trades": total,
        "total_pnl": total_pnl,
        "win_rate": wins / total if total > 0 else 0.0,
        "avg_pnl": total_pnl / total if total > 0 else 0.0,
        "best_trade": max((p.realized_pnl for p in closed_this_week), default=0.0),
        "worst_trade": min((p.realized_pnl for p in closed_this_week), default=0.0),
    }


def monthly_drawdown(equity_curve: List[float]) -> Dict[str, Any]:
    """Calculate monthly drawdown from an equity curve.

    Args:
        equity_curve: Daily equity values.

    Returns:
        Dictionary with max drawdown and drawdown series.
    """
    if not equity_curve or len(equity_curve) < 2:
        return {"max_drawdown": 0.0, "drawdowns": []}

    import numpy as np

    arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / np.where(peak != 0, peak, 1.0)
    max_dd = float(dd.min())

    return {
        "max_drawdown": max_dd,
        "current_drawdown": float(dd[-1]),
        "drawdowns": dd.tolist(),
    }


def trade_distribution(positions: List[Position]) -> Dict[str, Any]:
    """Analyze distribution of trade P&L.

    Args:
        positions: All positions.

    Returns:
        Distribution statistics.
    """
    closed = [p for p in positions if p.status == PositionStatus.CLOSED]
    if not closed:
        return {
            "count": 0,
            "mean_pnl": 0.0,
            "median_pnl": 0.0,
            "std_pnl": 0.0,
            "min_pnl": 0.0,
            "max_pnl": 0.0,
            "skewness": 0.0,
        }

    import numpy as np

    pnls = np.array([p.realized_pnl for p in closed])
    skew = float(np.mean(((pnls - pnls.mean()) / (pnls.std() + 1e-10)) ** 3)) if len(pnls) > 2 else 0.0

    return {
        "count": len(closed),
        "mean_pnl": float(pnls.mean()),
        "median_pnl": float(np.median(pnls)),
        "std_pnl": float(pnls.std()),
        "min_pnl": float(pnls.min()),
        "max_pnl": float(pnls.max()),
        "skewness": skew,
    }


def strategy_attribution(positions: List[Position]) -> Dict[str, Dict[str, Any]]:
    """Attribute P&L to each strategy.

    Args:
        positions: All positions.

    Returns:
        Per-strategy performance summary.
    """
    closed = [p for p in positions if p.status == PositionStatus.CLOSED]
    groups: Dict[str, List[Position]] = defaultdict(list)
    for p in closed:
        sid = p.strategy_id or "unknown"
        groups[sid].append(p)

    result: Dict[str, Dict[str, Any]] = {}
    for sid, trades in groups.items():
        pnls = [t.realized_pnl for t in trades]
        wins = sum(1 for pnl in pnls if pnl > 0)
        result[sid] = {
            "total_trades": len(trades),
            "total_pnl": sum(pnls),
            "win_rate": wins / len(trades) if trades else 0.0,
            "avg_pnl": sum(pnls) / len(pnls) if pnls else 0.0,
            "best_trade": max(pnls) if pnls else 0.0,
            "worst_trade": min(pnls) if pnls else 0.0,
        }

    return result


def full_report(
    equity_curve: List[float],
    positions: List[Position],
    benchmark_comparison: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Generate a full performance report.

    Args:
        equity_curve: Portfolio equity curve.
        positions: All positions.
        benchmark_comparison: Optional benchmark comparison dict.

    Returns:
        Complete report dictionary.
    """
    return {
        "summary": {
            "starting_capital": equity_curve[0] if equity_curve else 0.0,
            "current_value": equity_curve[-1] if equity_curve else 0.0,
            "total_return_pct": (
                ((equity_curve[-1] / equity_curve[0]) - 1.0) * 100
                if equity_curve and len(equity_curve) > 1 and equity_curve[0] != 0
                else 0.0
            ),
            "total_trades": len([p for p in positions if p.status == PositionStatus.CLOSED]),
            "open_positions": len([p for p in positions if p.status == PositionStatus.OPEN]),
        },
        "monthly_drawdown": monthly_drawdown(equity_curve),
        "trade_distribution": trade_distribution(positions),
        "strategy_attribution": strategy_attribution(positions),
        "benchmarks": benchmark_comparison or {},
    }
