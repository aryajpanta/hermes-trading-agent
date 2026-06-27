"""Decision audit logging — records every decision with full context."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.decision.models import DecisionLog, TradeRecommendation

# Module-level logger
logger = logging.getLogger("decision_engine")

# In-memory log store (for testing and runtime queries)
_decision_logs: List[DecisionLog] = []


def _json_default(o: Any) -> Any:
    """JSON fallback for non-native types (e.g. numpy bool_/float64/int64).

    numpy scalars from strategy math (e.g. ``np_float >= threshold`` yields a
    numpy.bool_) aren't JSON-serializable; coerce them to native Python types.
    """
    item = getattr(o, "item", None)
    if callable(item):
        try:
            return o.item()
        except Exception:
            pass
    return str(o)


def log_decision(
    symbol: str,
    input_data: Dict[str, Any],
    strategy_signals: List[Dict[str, Any]],
    aggregated_direction: float,
    aggregated_confidence: float,
    confidence_check: bool,
    agreement_check: bool,
    risk_checks: Dict[str, Any],
    recommendation: Optional[TradeRecommendation],
    reasoning: str,
) -> DecisionLog:
    """Create and store a decision log entry.

    Args:
        symbol: Asset symbol analyzed.
        input_data: Snapshot of input data.
        strategy_signals: Individual strategy signal dicts.
        aggregated_direction: Aggregated signal direction.
        aggregated_confidence: Aggregated confidence.
        confidence_check: Whether confidence threshold was met.
        agreement_check: Whether agreement threshold was met.
        risk_checks: Results of risk management checks.
        recommendation: Final recommendation (if any).
        reasoning: Human-readable reasoning.

    Returns:
        The created DecisionLog entry.
    """
    entry = DecisionLog(
        timestamp=datetime.utcnow(),
        symbol=symbol,
        input_data=input_data,
        strategy_signals=strategy_signals,
        aggregated_direction=aggregated_direction,
        aggregated_confidence=aggregated_confidence,
        confidence_check=confidence_check,
        agreement_check=agreement_check,
        risk_checks=risk_checks,
        recommendation=recommendation,
        reasoning=reasoning,
    )

    _decision_logs.append(entry)

    # Also log to Python logger for external consumers
    log_data = {
        "timestamp": entry.timestamp.isoformat(),
        "symbol": symbol,
        "direction": aggregated_direction,
        "confidence": aggregated_confidence,
        "confidence_check": confidence_check,
        "agreement_check": agreement_check,
        "risk_passed": risk_checks.get("all_passed", False),
        "recommendation": (
            recommendation.direction.value if recommendation else "NONE"
        ),
        "reasoning": reasoning,
    }
    logger.info("Decision: %s", json.dumps(log_data, default=_json_default))

    return entry


def get_decision_logs(
    symbol: Optional[str] = None, limit: int = 100
) -> List[DecisionLog]:
    """Retrieve stored decision logs.

    Args:
        symbol: Filter by symbol. If None, returns all.
        limit: Maximum number of entries to return.

    Returns:
        List of DecisionLog entries, most recent first.
    """
    logs = _decision_logs
    if symbol:
        logs = [l for l in logs if l.symbol == symbol]
    return list(reversed(logs[-limit:]))


def get_decision_count() -> int:
    """Return total number of logged decisions."""
    return len(_decision_logs)


def clear_decision_logs() -> None:
    """Clear all stored decision logs (for testing)."""
    _decision_logs.clear()


def format_recommendation(rec: TradeRecommendation) -> str:
    """Format a TradeRecommendation as a human-readable string.

    Args:
        rec: The trade recommendation to format.

    Returns:
        Formatted string.
    """
    lines = [
        f"{'=' * 60}",
        f"  TRADE RECOMMENDATION: {rec.symbol}",
        f"{'=' * 60}",
        f"  Direction:      {rec.direction.value}",
        f"  Confidence:     {rec.confidence:.2%}",
        f"  Entry Price:    ${rec.entry_price:.2f}",
        f"  Stop Loss:      ${rec.stop_loss:.2f}",
        f"  Take Profit:    ${rec.take_profit:.2f}",
        f"  Position Size:  {rec.position_size_pct:.2%}",
        f"  Risk/Reward:    {rec.risk_reward_ratio:.2f}",
        f"  Agreeing:       {', '.join(rec.strategies_agreeing)}",
        f"  Disagreeing:    {', '.join(rec.strategies_disagreeing) if rec.strategies_disagreeing else 'None'}",
        f"  Reasoning:      {rec.reasoning}",
        f"  Generated:      {rec.timestamp.isoformat()}",
        f"{'=' * 60}",
    ]
    return "\n".join(lines)
