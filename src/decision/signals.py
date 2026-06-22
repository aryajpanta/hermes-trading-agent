"""Signal aggregation — combines signals from multiple strategies weighted by performance."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from src.decision.models import Direction, StrategyPerformance
from src.strategy.signals import Signal


@dataclass
class AggregatedSignal:
    """Result of aggregating multiple strategy signals.

    Attributes:
        direction: Weighted aggregate direction (-1.0 to +1.0).
        confidence: Weighted aggregate confidence (0.0 to 1.0).
        agreeing: Strategy IDs whose signals agree with aggregate direction.
        disagreeing: Strategy IDs whose signals disagree.
        total_weight: Sum of weights used in aggregation.
        signal_details: Per-signal breakdown for debugging.
    """

    direction: float = 0.0
    confidence: float = 0.0
    agreeing: List[str] = field(default_factory=list)
    disagreeing: List[str] = field(default_factory=list)
    total_weight: float = 0.0
    signal_details: List[Dict[str, object]] = field(default_factory=list)


def aggregate_signals(
    signals: List[Signal],
    performance: Optional[Dict[str, StrategyPerformance]] = None,
    neutral_threshold: float = 0.1,
) -> AggregatedSignal:
    """Aggregate multiple strategy signals into a single direction and confidence.

    The aggregation is weighted by each strategy's historical performance.
    If no performance data is provided, equal weights are used.

    Args:
        signals: List of Strategy Signal objects.
        performance: Map from strategy_id to StrategyPerformance.
            If None, equal weights are used.
        neutral_threshold: Minimum absolute direction to consider non-neutral.

    Returns:
        AggregatedSignal with the combined direction and confidence.
    """
    if not signals:
        return AggregatedSignal(
            direction=0.0,
            confidence=0.0,
            agreeing=[],
            disagreeing=[],
        )

    if performance is None:
        performance = {}

    weighted_direction = 0.0
    weighted_confidence = 0.0
    total_weight = 0.0

    for sig in signals:
        if sig.strategy_id not in performance:
            perf = StrategyPerformance(
                strategy_id=sig.strategy_id,
                win_rate=0.5,
                profit_factor=1.0,
                sharpe_ratio=0.0,
                total_trades=0,
            )
        else:
            perf = performance[sig.strategy_id]

        weight = perf.weight
        weighted_direction += sig.direction * sig.confidence * weight
        weighted_confidence += sig.confidence * weight
        total_weight += weight

    if total_weight == 0:
        return AggregatedSignal(
            direction=0.0,
            confidence=0.0,
            agreeing=[],
            disagreeing=[],
        )

    agg_direction = weighted_direction / total_weight
    agg_confidence = weighted_confidence / total_weight

    # Clamp direction to [-1, 1]
    agg_direction = max(-1.0, min(1.0, agg_direction))
    # Clamp confidence to [0, 1]
    agg_confidence = max(0.0, min(1.0, agg_confidence))

    # Determine agreeing vs disagreeing
    agreeing: List[str] = []
    disagreeing: List[str] = []
    details: List[Dict[str, object]] = []

    for sig in signals:
        is_neutral = abs(sig.direction) < neutral_threshold
        if is_neutral:
            # Neutral signals neither agree nor disagree strongly
            details.append(
                {
                    "strategy_id": sig.strategy_id,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "status": "neutral",
                }
            )
            continue

        sig_direction_sign = 1.0 if sig.direction > 0 else -1.0
        agg_sign = 1.0 if agg_direction > 0 else (-1.0 if agg_direction < 0 else 0.0)

        if sig_direction_sign == agg_sign or agg_direction == 0.0:
            agreeing.append(sig.strategy_id)
            details.append(
                {
                    "strategy_id": sig.strategy_id,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "status": "agreeing",
                }
            )
        else:
            disagreeing.append(sig.strategy_id)
            details.append(
                {
                    "strategy_id": sig.strategy_id,
                    "direction": sig.direction,
                    "confidence": sig.confidence,
                    "status": "disagreeing",
                }
            )

    return AggregatedSignal(
        direction=agg_direction,
        confidence=agg_confidence,
        agreeing=agreeing,
        disagreeing=disagreeing,
        total_weight=total_weight,
        signal_details=details,
    )


def direction_from_signal(direction_value: float) -> Direction:
    """Convert a numeric direction to a Direction enum.

    Args:
        direction_value: Numeric direction (-1.0 to +1.0).

    Returns:
        Direction.BUY, Direction.SELL, or Direction.HOLD.
    """
    if direction_value > 0.1:
        return Direction.BUY
    elif direction_value < -0.1:
        return Direction.SELL
    return Direction.HOLD
