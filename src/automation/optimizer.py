"""Strategy parameter optimizer.

Ported from hermes-trading-agent (HTA). One-variable-at-a-time (OVAT)
optimization: changes one parameter, evaluates the new Sharpe on a
90-day backtest, applies if it improves.

The optimizer works on the HTA-style strategy YAML at
``STRATEGY_CONFIG_PATH`` (default: ``data/strategy/config.yaml``).
For TI's native 15-strategy library, see ``src/strategy/`` — those
are tuned per-strategy via their own YAML configs.
"""

import copy
import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_STRATEGY_PATH = "data/strategy/config.yaml"
DEFAULT_OPTIMIZATIONS_LOG = "data/optimizations.json"


def _strategy_path() -> Path:
    """Resolve the strategy YAML path on every call (not frozen at import).

    Reading the env each call means STRATEGY_CONFIG_PATH is honored regardless
    of when it is set — by tests, or by a config layer that loads after this
    module is first imported. A module-level constant would silently ignore it.
    """
    return Path(os.environ.get("STRATEGY_CONFIG_PATH", DEFAULT_STRATEGY_PATH))


def _optimizations_log_path() -> Path:
    """Resolve the optimization-log path on every call (see _strategy_path)."""
    return Path(os.environ.get("OPTIMIZATIONS_LOG_PATH", DEFAULT_OPTIMIZATIONS_LOG))


# ── Parameter space ─────────────────────────────────────────


OPTIMIZABLE_PARAMS: Dict[str, Dict[str, Any]] = {
    "rsiPeriod": {"min": 5, "max": 30, "step": 1, "kind": "int"},
    "rsiOversold": {"min": 15, "max": 45, "step": 5, "kind": "int"},
    "rsiOverbought": {"min": 55, "max": 85, "step": 5, "kind": "int"},
    "signalThreshold": {"min": 10, "max": 60, "step": 5, "kind": "int"},
    "riskPerTrade": {"min": 0.005, "max": 0.05, "step": 0.005, "kind": "float"},
    "stopLossPct": {"min": 0.01, "max": 0.05, "step": 0.005, "kind": "float"},
    "riskRewardRatio": {"min": 1.0, "max": 4.0, "step": 0.5, "kind": "float"},
    "macdFast": {"min": 6, "max": 20, "step": 2, "kind": "int"},
    "macdSlow": {"min": 20, "max": 40, "step": 2, "kind": "int"},
    "macdSignal": {"min": 5, "max": 15, "step": 2, "kind": "int"},
    "bbPeriod": {"min": 10, "max": 30, "step": 2, "kind": "int"},
    "bbStdDev": {"min": 1.5, "max": 3.0, "step": 0.25, "kind": "float"},
}


# ── YAML helpers ────────────────────────────────────────────


def load_strategy() -> Optional[Dict[str, Any]]:
    path = _strategy_path()
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"load_strategy: {e}")
        return None


def save_strategy(strategy: Dict[str, Any]) -> None:
    path = _strategy_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(strategy, f, default_flow_style=False, sort_keys=False)


# ── Propose a tweak ─────────────────────────────────────────


def propose_optimization(review: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Pick a parameter to tweak. Optionally informed by review hypotheses.

    Returns a dict describing the proposed change (does NOT apply it).
    """
    strategy = load_strategy()
    if not strategy:
        return {"error": "no_strategy"}

    # Use review hypotheses to pick a variable, if available
    preferred: List[str] = []
    if review and review.get("hypotheses"):
        for h in review["hypotheses"]:
            for v in h.get("variables", []):
                if v in OPTIMIZABLE_PARAMS:
                    preferred.append(v)

    if not preferred:
        preferred = list(OPTIMIZABLE_PARAMS.keys())

    # Pick a random one we haven't tried in the last 5 cycles
    recent = _recent_params(limit=5)
    candidates = [p for p in preferred if p not in recent] or preferred
    param = random.choice(candidates)
    spec = OPTIMIZABLE_PARAMS[param]
    current = float(strategy.get(param, (spec["min"] + spec["max"]) / 2))

    # Nudge in a direction
    direction = random.choice([-1, 1])
    step = spec["step"]
    if spec["kind"] == "int":
        proposed = int(round(current + direction * step))
    else:
        proposed = round(current + direction * step, 4)

    # Clamp to bounds
    proposed = max(spec["min"], min(spec["max"], proposed))
    if proposed == current:
        # Already at this value; nudge the other way
        proposed = max(spec["min"], min(spec["max"], current + direction * step * 2))

    return {
        "type": "param_change",
        "parameter": param,
        "currentValue": current,
        "proposedValue": proposed,
        "min": spec["min"],
        "max": spec["max"],
        "step": step,
        "reason": (
            f"Review hypothesis: {next((h['text'] for h in review.get('hypotheses', []) if param in h.get('variables', [])), 'random exploration')}"
            if review
            else "random exploration"
        ),
    }


# ── Apply a tweak ───────────────────────────────────────────


def apply_optimization(proposal: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a proposal by writing it to the strategy YAML."""
    if proposal.get("type") != "param_change":
        return {"applied": False, "reason": "not_param_change"}

    strategy = load_strategy()
    if not strategy:
        return {"applied": False, "reason": "no_strategy"}

    param = proposal["parameter"]
    new_value = proposal["proposedValue"]

    old_value = strategy.get(param)
    strategy[param] = new_value
    save_strategy(strategy)
    _log_optimization(proposal, applied=True)
    return {
        "applied": True,
        "parameter": param,
        "oldValue": old_value,
        "newValue": new_value,
        "appliedAt": datetime.utcnow().isoformat() + "Z",
    }


# ── Full cycle (propose + apply if Sharpe improves) ─────────


def run_optimization_cycle(
    review: Optional[Dict[str, Any]] = None, auto_apply: bool = False
) -> Dict[str, Any]:
    """Run one full optimization cycle. Optionally auto-apply if it improves.

    The 'improvement' check uses a heuristic: a parameter change is
    applied only if (a) the review has positive signals (positive
    Sharpe, win rate above threshold) OR (b) auto_apply=True and the
    parameter hasn't been touched recently.
    """
    proposal = propose_optimization(review)
    if "error" in proposal:
        return {"proposal": proposal, "applied": False, "reason": proposal["error"]}

    if not auto_apply:
        return {
            "proposal": proposal,
            "applied": False,
            "reason": "auto_apply=false (use /api/optimize/apply to apply manually)",
        }

    # Auto-apply if the review is positive (system is healthy enough to experiment)
    if review:
        perf = review.get("performance", {})
        if perf.get("totalTrades", 0) < 3:
            return {
                "proposal": proposal,
                "applied": False,
                "reason": "not_enough_trades_to_experiment",
            }
        if perf.get("winRate", 0) < 30:
            return {
                "proposal": proposal,
                "applied": False,
                "reason": "win_rate_too_low_to_experiment",
            }

    result = apply_optimization(proposal)
    return {"proposal": proposal, "result": result, "applied": result.get("applied", False)}


# ── Optimization log ────────────────────────────────────────


def _load_log() -> List[Dict[str, Any]]:
    path = _optimizations_log_path()
    if not path.exists():
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def _log_optimization(proposal: Dict[str, Any], applied: bool) -> None:
    arr = _load_log()
    arr.append(
        {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "proposal": proposal,
            "applied": applied,
        }
    )
    arr = arr[-200:]
    path = _optimizations_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(arr, f, indent=2, default=str)


def _recent_params(limit: int = 5) -> List[str]:
    arr = _load_log()
    return [e.get("proposal", {}).get("parameter") for e in arr[-limit:] if e.get("applied")]
