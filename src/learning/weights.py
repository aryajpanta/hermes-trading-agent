"""Weight manager — adjusts strategy weights based on recent performance.

Weight adjustment logic:
- Base: equal weight across all strategies.
- Adjustment: weight by recent Sharpe ratio with exponential decay.
- Bounds: min 0.05, max 0.30 per strategy.
"""

import math
from typing import Dict, Optional

from src.learning.tracker import StrategyPerformance


# Bounds
MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.30
DECAY_HALF_LIFE_PERIODS = 3  # Sharpe values older than this are halved


class WeightManager:
    """Compute and maintain normalized strategy weights based on performance.

    Usage:
        wm = WeightManager()
        weights = wm.recalculate_weights(performance_map)
        current = wm.get_weights()
    """

    def __init__(self, strategy_ids: Optional[list[str]] = None) -> None:
        """Initialize the weight manager.

        Args:
            strategy_ids: Known strategy IDs for equal-weight defaults.
                If None, weights are set dynamically on first recalculate.
        """
        self._weights: Dict[str, float] = {}
        if strategy_ids:
            n = len(strategy_ids)
            eq = 1.0 / n if n > 0 else 0.0
            self._weights = {sid: eq for sid in strategy_ids}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def recalculate_weights(
        self,
        performance: Dict[str, StrategyPerformance],
        decay_halflife: int = DECAY_HALF_LIFE_PERIODS,
    ) -> Dict[str, float]:
        """Recalculate strategy weights from performance metrics.

        Algorithm:
        1. Start with equal base weight for each strategy.
        2. Compute a raw score from Sharpe ratio (higher is better).
        3. Apply exponential decay to older data implicitly via the
           Sharpe computed over the chosen period.
        4. Normalize scores to sum to 1.0.
        5. Clamp each weight to [MIN_WEIGHT, MAX_WEIGHT].
        6. Re-normalize after clamping.

        Args:
            performance: Map of strategy_id -> StrategyPerformance.
            decay_halflife: Half-life in periods for exponential decay
                (used to penalize strategies with fewer data points).

        Returns:
            Dictionary mapping strategy_id -> normalized weight.
        """
        if not performance:
            return {}

        strategies = list(performance.keys())
        n = len(strategies)

        # Step 1: Base equal weight
        base = 1.0 / n

        # Step 2: Compute raw scores from Sharpe ratio
        # We blend the base equal weight with a performance-adjusted weight
        # using a 70/30 split so that the Sharpe signal is moderate and
        # doesn't cause all strategies to hit the MAX_WEIGHT cap.
        raw_scores: Dict[str, float] = {}
        for sid, perf in performance.items():
            sharpe = perf.sharpe_ratio

            # Map Sharpe to [0.5, 1.5] range (moderate influence)
            # Sharpe 0 -> 1.0, Sharpe 2 -> 1.5, Sharpe -1 -> 0.5
            sharpe_mapped = max(0.5, min(1.5, 1.0 + sharpe * 0.25))

            # Step 3: Apply data-sufficiency decay
            # Strategies with fewer trades get penalized
            data_factor = self._data_sufficiency_factor(
                perf.signals_taken, decay_halflife
            )

            # Blend: 70% base weight + 30% performance-adjusted weight
            perf_component = base * sharpe_mapped * data_factor
            blended = 0.7 * base + 0.3 * perf_component
            raw_scores[sid] = blended

        # Step 4: Normalize raw scores
        total_score = sum(raw_scores.values())
        if total_score <= 0:
            # Fallback to equal weights
            return {sid: base for sid in strategies}

        normalized = {sid: sc / total_score for sid, sc in raw_scores.items()}

        # Step 5: Clamp to [MIN_WEIGHT, MAX_WEIGHT]
        # Only enforce MAX_WEIGHT if it's feasible (i.e., 1/N <= MAX_WEIGHT).
        # With very few strategies, equal weight may already exceed the cap.
        effective_max = MAX_WEIGHT if base <= MAX_WEIGHT else min(1.0, base * 1.2)
        clamped = {
            sid: max(MIN_WEIGHT, min(effective_max, w))
            for sid, w in normalized.items()
        }

        # Step 6: Re-normalize after clamping
        total_clamped = sum(clamped.values())
        if total_clamped <= 0:
            return {sid: base for sid in strategies}

        final = {sid: w / total_clamped for sid, w in clamped.items()}

        self._weights = final
        return dict(final)

    def get_weights(self) -> Dict[str, float]:
        """Get current strategy weights.

        Returns:
            Dictionary mapping strategy_id -> weight (sums to 1.0).
        """
        return dict(self._weights)

    def set_weights(self, weights: Dict[str, float]) -> None:
        """Manually set strategy weights (will be normalized).

        Args:
            weights: Desired weights (will be normalized to sum to 1.0).
        """
        total = sum(weights.values())
        if total <= 0:
            return
        self._weights = {sid: w / total for sid, w in weights.items()}

    # ------------------------------------------------------------------
    # Adaptation
    # ------------------------------------------------------------------

    def adapt_to_regime(
        self,
        regime: str,
        regime_strategy_bias: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """Adjust weights for a detected market regime.

        Applies multiplicative bias to current weights based on regime.

        Args:
            regime: Current market regime ('bull', 'bear', 'sideways',
                'high_volatility').
            regime_strategy_bias: Optional override mapping strategy_ids
                to multipliers. If None, uses built-in defaults.

        Returns:
            Updated weights dictionary.
        """
        if not self._weights:
            return {}

        bias = regime_strategy_bias or self._get_default_regime_bias(regime)

        adapted: Dict[str, float] = {}
        for sid, w in self._weights.items():
            multiplier = bias.get(sid, 1.0)
            adapted[sid] = w * multiplier

        # Re-normalize
        total = sum(adapted.values())
        if total <= 0:
            return dict(self._weights)

        adapted = {sid: v / total for sid, v in adapted.items()}

        # Clamp again
        adapted = {
            sid: max(MIN_WEIGHT, min(MAX_WEIGHT, v))
            for sid, v in adapted.items()
        }

        # Final re-normalize
        total = sum(adapted.values())
        if total > 0:
            adapted = {sid: v / total for sid, v in adapted.items()}

        self._weights = adapted
        return dict(adapted)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _data_sufficiency_factor(
        signals_taken: int, halflife: int = DECAY_HALF_LIFE_PERIODS
    ) -> float:
        """Exponential decay factor based on number of trades.

        Strategies with very few trades get a penalty so that well-tested
        strategies are preferred.

        Args:
            signals_taken: Number of trades taken.
            halflife: Number of trades at which the factor is 0.5.

        Returns:
            Factor between 0.0 and 1.0.
        """
        if signals_taken <= 0:
            return 0.1  # Minimum factor for untested strategies
        # Exponential decay: factor = 2^(-signals/halflife)
        # But we want MORE trades to be BETTER, so we invert:
        # factor = 1 - 2^(-signals/halflife)
        # At signals=0: factor=0, at signals=halflife: factor=0.5
        # We add a floor so untested strategies still get some weight
        raw = 1.0 - math.pow(2.0, -signals_taken / halflife)
        return max(0.1, min(raw, 1.0))

    @staticmethod
    def _get_default_regime_bias(regime: str) -> Dict[str, float]:
        """Get default regime-based strategy biases.

        These are generic multipliers — strategies with matching categories
        get a boost, others get a reduction.

        Args:
            regime: Market regime string.

        Returns:
            Dictionary of default multipliers (empty = no bias).
        """
        # The actual per-strategy mapping would depend on strategy categories.
        # Here we provide generic adjustments that the caller can override.
        if regime == "bull":
            # Trend-following strategies get a boost
            return {}  # Caller should supply per-strategy mapping
        elif regime == "bear":
            return {}
        elif regime == "sideways":
            return {}
        elif regime == "high_volatility":
            return {}
        return {}
