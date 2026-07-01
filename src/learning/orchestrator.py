"""Orchestrator — single entry point for the tick loop to call.

Public API:
  on_trade_entry(symbol, strategy_id, qty, entry_price)
  on_trade_close(exit_prices: {symbol: price})
  get_current_weights() -> {strategy_id: weight}
  status() -> dict (for /api/learning/status endpoint)

This is what the existing tick loop will call. Internally it manages:
  - LabelingBuilder (feature snapshot + close label)
  - OnlineLearner (LightGBM)
  - LiveWeightAdapter (model → weights)
  - ValidationGate (Sharpe guard)
  - LearnerScheduler (retrain cadence)
"""
from __future__ import annotations
import logging
from typing import Dict, List, Optional

from src.learning.labeling.builder import LabelingBuilder
from src.learning.model.online import OnlineLearner
from src.learning.weighting.live import LiveWeightAdapter
from src.learning.validation.gate import ValidationGate
from src.learning.validation.backtester import backtest_weights
from src.learning.scheduler import LearnerScheduler

logger = logging.getLogger(__name__)


class LearningOrchestrator:
    def __init__(
        self,
        retrain_every_n: int = 5,
        data_dir: str = "data/learning",
        min_trades_for_retrain: int = 20,
    ) -> None:
        self.data_dir = data_dir
        self.min_trades = min_trades_for_retrain
        self.labeler = LabelingBuilder(data_dir=data_dir)
        self.learner = OnlineLearner(model_path=f"{data_dir}/model.txt")
        self.adapter = LiveWeightAdapter()
        self.gate = ValidationGate(log_path=f"{data_dir}/gate_log.jsonl")
        self.scheduler = LearnerScheduler(
            retrain_every_n=retrain_every_n,
            state_path=f"{data_dir}/scheduler_state.json",
        )
        # Initialize closed_trade_count from current state
        self._closed_count = self.scheduler.state.last_retrain_trade_count

    def on_trade_entry(
        self, symbol: str, strategy_id: str, qty: float, entry_price: float,
    ) -> None:
        self.labeler.record_entry(symbol, strategy_id, qty, entry_price)

    def on_trade_close(self, exit_prices: Dict[str, float]) -> None:
        labeled = self.labeler.close_pending(exit_prices)
        if not labeled:
            return
        self._closed_count += len(labeled)
        if self.scheduler.should_retrain(self._closed_count):
            self._retrain_and_publish()

    def _retrain_and_publish(self) -> None:
        df = self.labeler.load_all()
        if df.empty or len(df) < self.min_trades:
            logger.info(
                "retrain skipped: only %d rows (need %d)",
                len(df), self.min_trades,
            )
            return
        # Use the most recent data for warm-start; full data for first fit
        if self.learner._model is None:
            self.learner.fit(df)
        else:
            # Train on most recent data
            self.learner.partial_fit(df.tail(200))
        # Get per-strategy expected PnL
        if "strategy_id" not in df.columns:
            logger.warning("no strategy_id in labeled data; skipping weight update")
            return
        recent = df.tail(200)
        expected = self.learner.per_strategy_expected_pnl(recent)
        candidate_weights = self.adapter.from_expected_pnl(expected)
        if not candidate_weights:
            logger.info("no candidate weights produced; skipping")
            return
        # Backtest the candidate vs current (using our own closed trades as the
        # trade-replay set). Convert the labeled DataFrame into a trades list.
        try:
            trades_for_bt = self._df_to_trades(df.tail(200))
            current_sharpe = (
                self.scheduler.state.current_sharpe
                if self.scheduler.state.published_weights else 0.0
            )
            candidate_sharpe = backtest_weights(
                candidate_weights, trades=trades_for_bt,
            )
            decision = self.gate.evaluate(
                candidate_weights, current_sharpe, candidate_sharpe,
            )
            if decision.accepted:
                self.scheduler.mark_retrained(
                    candidate_weights, candidate_sharpe, self._closed_count,
                )
                logger.info(
                    "learning: published new weights (%d strategies, Sharpe %.3f)",
                    len(candidate_weights), candidate_sharpe,
                )
            else:
                logger.info(
                    "learning: gate rejected new weights: %s", decision.reason
                )
        except Exception as e:
            logger.warning(
                "backtest/gate error: %s — keeping current weights", e,
            )

    def _df_to_trades(self, df) -> List[Dict]:
        """Convert labeled DataFrame to a trades list for backtesting."""
        trades = []
        for _, row in df.iterrows():
            trades.append({
                "pnl": float(row.get("realized_pnl_pct", 0.0)),
                "strategy_id": str(row.get("strategy_id", "")),
                "symbol": str(row.get("symbol", "")),
                "exit_ts": str(row.get("exit_ts", "")),
            })
        return trades

    def get_current_weights(self) -> Dict[str, float]:
        if self.scheduler.state.published_weights:
            return dict(self.scheduler.state.published_weights)
        return {}

    def status(self) -> dict:
        return {
            "closed_trade_count": self._closed_count,
            "last_retrain_ts": self.scheduler.state.last_retrain_ts,
            "current_weights": self.get_current_weights(),
            "current_sharpe": self.scheduler.state.current_sharpe,
            "feature_importance": self.learner.feature_importance(),
            "model_loaded": self.learner._model is not None,
            "min_trades_for_retrain": self.min_trades,
            "retrain_every_n": self.scheduler.retrain_every_n,
        }
