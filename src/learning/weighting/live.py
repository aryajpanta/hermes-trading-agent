"""Map model's per-strategy expected PnL into normalized weights in [0.05, 0.30].

Same bounds as HTA's existing WeightManager — keeps compatibility with the
DecisionEngine's downstream consumers.

Algorithm: softmax over expected PnL → project onto the lower-bounded simplex
{x : sum(x) = 1, lo <= x_i} (no upper bound, since with N strategies
the [lo, hi] box is infeasible for small N — e.g. 3 strategies with
hi=0.30 gives sum_hi=0.9 < 1.0). The upper bound is enforced as a soft cap
by the softmax temperature and the renormalization step.

For N=15 (the actual HTA system), 0.30*15 = 4.5 >> 1.0, so the upper bound
is effectively never reached.
"""
from __future__ import annotations
import math
from typing import Dict, List

MIN_WEIGHT = 0.05
MAX_WEIGHT = 0.30  # soft cap; not strictly enforced for small N


def _project_lower_simplex(v: List[float], lo: float) -> List[float]:
    """Project v onto {x : sum(x)=1, x_i >= lo}.

    Returns equal weights if lo*n > 1 (infeasible).
    """
    n = len(v)
    if n == 0:
        return []
    if lo * n > 1.0 + 1e-9:
        return [1.0 / n] * n
    # Sort v in descending order
    u = sorted(v, reverse=True)
    # Find rho: largest j such that u[j] - (sum(u[0..j]) - 1) / (j+1) >= lo
    cssv = 0.0
    rho = -1
    for j in range(n):
        cssv += u[j]
        if u[j] - (cssv - 1.0) / (j + 1) >= lo:
            rho = j
    if rho < 0:
        return [1.0 / n] * n
    tau = (cssv - 1.0) / (rho + 1)
    return [max(lo, vi - tau) for vi in v]


class LiveWeightAdapter:
    def from_expected_pnl(
        self, expected: Dict[str, float], temperature: float = 0.02
    ) -> Dict[str, float]:
        """Softmax over expected PnL, projected to lower-bounded simplex.

        Args:
            expected: {strategy_id: expected_pnl_pct} (e.g. 0.02 = 2% expected PnL)
            temperature: softmax temperature. Lower = sharper weight differences.
                0.02 means a 2% PnL difference = ~e^1 = 2.7× weight ratio.

        Returns:
            {strategy_id: weight} summing to 1.0, all >= MIN_WEIGHT.
            Soft-capped at MAX_WEIGHT (renormalized, so may slightly exceed when N is small).
        """
        if not expected:
            return {}
        keys = list(expected.keys())
        vals = [expected[k] for k in keys]
        # Softmax
        exps = [math.exp(v / temperature) for v in vals]
        total = sum(exps)
        if total <= 0:
            n = len(keys)
            return {k: 1.0 / n for k in keys} if n else {}
        raw = [e / total for e in exps]
        # Project onto lower-bounded simplex
        projected = _project_lower_simplex(raw, MIN_WEIGHT)
        # Soft cap: clamp each to MAX_WEIGHT, then renormalize
        capped = [min(MAX_WEIGHT, w) for w in projected]
        csum = sum(capped)
        if csum > 0:
            capped = [w / csum for w in capped]
        return {k: float(w) for k, w in zip(keys, capped)}
