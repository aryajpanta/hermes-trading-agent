"""Backtest validation gate — only publish new weights if they don't tank Sharpe.

Lightweight by design: takes pre-computed Sharpe values (the backtester
computes them) and makes a yes/no decision with audit logging.
"""
from __future__ import annotations
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

DEFAULT_LOG_PATH = "data/learning/gate_log.jsonl"


@dataclass
class GateDecision:
    accepted: bool
    reason: str
    current_sharpe: float
    candidate_sharpe: float
    pct_change: float
    timestamp: float
    weights: Dict[str, float]


class ValidationGate:
    def __init__(
        self, max_drop_pct: float = 0.05, log_path: str = DEFAULT_LOG_PATH,
    ) -> None:
        self.max_drop_pct = max_drop_pct
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def evaluate(
        self,
        candidate_weights: Dict[str, float],
        current_sharpe: float,
        candidate_sharpe: float,
    ) -> GateDecision:
        """Decide whether to accept new weights based on Sharpe comparison.

        Rules:
        - current_sharpe <= 0: accept any non-negative candidate (no baseline)
        - improvement: always accept
        - within max_drop_pct tolerance: accept
        - beyond tolerance: reject
        """
        if current_sharpe <= 0:
            accepted = candidate_sharpe >= 0
            reason = "no_baseline_accepted" if accepted else "candidate_negative"
            pct_change = 0.0
        else:
            pct_change = (candidate_sharpe - current_sharpe) / current_sharpe
            if pct_change >= 0:
                accepted = True
                reason = "improved_or_equal"
            elif pct_change >= -self.max_drop_pct:
                accepted = True
                reason = f"within_tolerance ({pct_change:+.1%})"
            else:
                accepted = False
                reason = (
                    f"rejected_sharpe_drop ({pct_change:+.1%} > "
                    f"{self.max_drop_pct:.0%} tolerance)"
                )
        decision = GateDecision(
            accepted=accepted,
            reason=reason,
            current_sharpe=current_sharpe,
            candidate_sharpe=candidate_sharpe,
            pct_change=pct_change,
            timestamp=time.time(),
            weights=dict(candidate_weights),
        )
        self._log(decision)
        return decision

    def _log(self, d: GateDecision) -> None:
        with open(self.log_path, "a") as f:
            f.write(json.dumps(asdict(d), default=str) + "\n")
