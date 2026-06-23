"""Daily performance review — analyzes closed trades and generates hypotheses.

Ported from hermes-trading-agent (HTA) to Python. Runs once every 24h
(default) via the automation scheduler.

Output: a review record with performance metrics, per-symbol breakdown,
and a list of hypotheses for the optimizer to act on.
"""

import json
import logging
import math
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.execution.paper import PaperTrader

logger = logging.getLogger(__name__)

REVIEWS_DIR = Path("data/reviews")
LATEST_PATH = REVIEWS_DIR / "latest.json"


def _load_latest() -> Optional[Dict[str, Any]]:
    if not LATEST_PATH.exists():
        return None
    try:
        with open(LATEST_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save(review: Dict[str, Any]) -> None:
    REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    with open(LATEST_PATH, "w") as f:
        json.dump(review, f, indent=2, default=str)
    # Also keep a cycle-numbered copy
    cycle = review.get("cycle", 0)
    cycle_path = REVIEWS_DIR / f"cycle_{cycle}.json"
    with open(cycle_path, "w") as f:
        json.dump(review, f, indent=2, default=str)


# ── Performance metrics ─────────────────────────────────────


def _calc_metrics(closed_trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute performance metrics from a list of closed trades."""
    if not closed_trades:
        return {
            "totalTrades": 0,
            "wins": 0,
            "losses": 0,
            "winRate": 0.0,
            "totalPnl": 0.0,
            "avgPnl": 0.0,
            "sharpeRatio": 0.0,
            "maxDrawdownPct": 0.0,
        }

    pnls = [float(t.get("pnl", 0)) for t in closed_trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    total = sum(pnls)
    avg = total / len(pnls)
    win_rate = (len(wins) / len(pnls)) * 100.0 if pnls else 0.0

    # Sharpe: mean(pnl) / std(pnl), annualized
    if len(pnls) > 1:
        mean = sum(pnls) / len(pnls)
        var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(var) if var > 0 else 1e-9
        sharpe = (mean / std) * math.sqrt(252) if std else 0.0
    else:
        sharpe = 0.0

    # Max drawdown from cumulative pnl
    cumulative = 0.0
    peak = 0.0
    max_dd = 0.0
    for p in pnls:
        cumulative += p
        peak = max(peak, cumulative)
        dd = (peak - cumulative) / 100_000.0  # normalized to starting balance
        max_dd = max(max_dd, dd)

    return {
        "totalTrades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "winRate": round(win_rate, 2),
        "totalPnl": round(total, 4),
        "avgPnl": round(avg, 4),
        "sharpeRatio": round(sharpe, 3),
        "maxDrawdownPct": round(max_dd * 100, 2),
    }


def _analyze_by_symbol(
    closed_trades: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    by_symbol: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"trades": 0, "wins": 0, "losses": 0, "totalPnl": 0.0}
    )
    for t in closed_trades:
        sym = t.get("symbol", "unknown")
        s = by_symbol[sym]
        s["trades"] += 1
        pnl = float(t.get("pnl", 0))
        s["totalPnl"] += pnl
        if pnl > 0:
            s["wins"] += 1
        else:
            s["losses"] += 1
    for s in by_symbol.values():
        s["winRate"] = round((s["wins"] / s["trades"]) * 100, 2) if s["trades"] else 0
        s["totalPnl"] = round(s["totalPnl"], 4)
    return dict(by_symbol)


def _generate_hypotheses(
    performance: Dict[str, Any],
    by_symbol: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Generate plain-English hypotheses for the optimizer."""
    hyp: List[Dict[str, Any]] = []

    if performance["totalTrades"] < 5:
        hyp.append(
            {
                "id": "low_sample_size",
                "severity": "low",
                "text": "Not enough closed trades for reliable statistics.",
                "variables": [],
            }
        )
        return hyp

    # Win rate too low
    if performance["winRate"] < 40:
        hyp.append(
            {
                "id": "low_win_rate",
                "severity": "high",
                "text": (
                    f"Win rate is {performance['winRate']}% (target 40%+). "
                    f"Consider tightening entry signals or increasing min_confidence."
                ),
                "variables": ["min_confidence"],
            }
        )

    # Negative Sharpe
    if performance["sharpeRatio"] < 0:
        hyp.append(
            {
                "id": "negative_sharpe",
                "severity": "high",
                "text": (
                    f"Sharpe ratio is {performance['sharpeRatio']} (target 1+). "
                    f"Consider wider stops or better trend filters."
                ),
                "variables": ["stop_loss_pct"],
            }
        )

    # Per-symbol bias
    for sym, stats in by_symbol.items():
        if stats["trades"] >= 3 and stats["winRate"] < 30:
            hyp.append(
                {
                    "id": f"underperforming_{sym}",
                    "severity": "medium",
                    "text": (
                        f"{sym} has {stats['winRate']}% win rate over "
                        f"{stats['trades']} trades. Consider excluding or "
                        f"tuning its strategy."
                    ),
                    "variables": [f"symbol_filter.{sym}"],
                }
            )

    return hyp


def _generate_report(review: Dict[str, Any]) -> str:
    p = review["performance"]
    md = [
        f"# Daily Review — Cycle {review['cycle']}",
        f"_{review['timestamp']}_",
        "",
        "## Performance",
        f"- Total trades: **{p['totalTrades']}**",
        f"- Win rate: **{p['winRate']}%**",
        f"- Total P&L: **${p['totalPnl']:,.2f}**",
        f"- Avg P&L/trade: ${p['avgPnl']:,.4f}",
        f"- Sharpe ratio: {p['sharpeRatio']}",
        f"- Max drawdown: {p['maxDrawdownPct']}%",
        "",
        "## By Symbol",
    ]
    for sym, s in review.get("bySymbol", {}).items():
        md.append(
            f"- **{sym}**: {s['trades']} trades, "
            f"{s['winRate']}% wins, ${s['totalPnl']:,.2f} P&L"
        )
    if review.get("hypotheses"):
        md += ["", "## Hypotheses"]
        for h in review["hypotheses"]:
            md.append(f"- [{h['severity']}] {h['text']}")
    return "\n".join(md)


# ── Public API ──────────────────────────────────────────────


def run_review_cycle() -> Dict[str, Any]:
    """Run a full review cycle. Returns the review dict."""
    trader = PaperTrader()
    history = trader.get_history() or []
    closed = [t for t in history if t.get("type") == "exit" or t.get("status") == "closed"]

    performance = _calc_metrics(closed)
    by_symbol = _analyze_by_symbol(closed)
    hypotheses = _generate_hypotheses(performance, by_symbol)

    prev = _load_latest()
    cycle = (prev.get("cycle", 0) if prev else 0) + 1

    review = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "cycle": cycle,
        "performance": performance,
        "bySymbol": by_symbol,
        "hypotheses": hypotheses,
    }
    review["reportText"] = _generate_report(review)

    _save(review)
    logger.info(
        f"[Review] cycle {cycle}: {performance['totalTrades']} trades, "
        f"win rate {performance['winRate']}%, "
        f"Sharpe {performance['sharpeRatio']}"
    )
    return review


def get_latest_review() -> Optional[Dict[str, Any]]:
    return _load_latest()
