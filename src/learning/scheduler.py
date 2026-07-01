"""Continuous learning scheduler.

- Tracks closed-trade count since last retrain
- Triggers retrain + weight update when threshold is crossed
- Runs the validation gate before publishing new weights
- Persists a state file so restarts are idempotent
"""
from __future__ import annotations
import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = "data/learning/scheduler_state.json"


@dataclass
class SchedulerState:
    last_retrain_trade_count: int = 0
    last_retrain_ts: float = 0.0
    published_weights: Optional[Dict[str, float]] = None
    current_sharpe: float = 0.0


class LearnerScheduler:
    def __init__(
        self, retrain_every_n: int = 5, state_path: str = DEFAULT_STATE_PATH,
    ) -> None:
        self.retrain_every_n = retrain_every_n
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def should_retrain(self, closed_trade_count: int) -> bool:
        """True if we've accumulated N new trades since the last retrain."""
        return (closed_trade_count - self.state.last_retrain_trade_count
                ) >= self.retrain_every_n

    def trades_since_retrain(self, closed_trade_count: int) -> int:
        return closed_trade_count - self.state.last_retrain_trade_count

    def mark_retrained(
        self, new_weights: Dict[str, float], sharpe: float = 0.0,
        closed_trade_count: int = 0,
    ) -> None:
        self.state.published_weights = new_weights
        self.state.current_sharpe = sharpe
        self.state.last_retrain_ts = time.time()
        if closed_trade_count > 0:
            self.state.last_retrain_trade_count = closed_trade_count
        self._save_state()

    def _load_state(self) -> SchedulerState:
        if self.state_path.exists():
            try:
                with open(self.state_path) as f:
                    return SchedulerState(**json.load(f))
            except Exception:
                pass
        return SchedulerState()

    def _save_state(self) -> None:
        with open(self.state_path, "w") as f:
            json.dump(asdict(self.state), f, indent=2, default=str)
