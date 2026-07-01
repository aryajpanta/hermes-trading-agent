"""Online learner — LightGBM regressor predicting realized PnL.

Two modes:
- fit(df): train from scratch on a labeled DataFrame
- partial_fit(df): warm-start retrain on new data (continues from current model)

Predictions are made per (symbol, strategy_id) tuple conditioned on features.
The model is persisted to data/learning/model.txt and reloaded on startup.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

from src.learning.features.schema import FEATURE_COLUMNS, LABEL_COLUMN

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = "data/learning/model.txt"


class OnlineLearner:
    def __init__(self, model_path: str = DEFAULT_MODEL_PATH) -> None:
        self.model_path = Path(model_path)
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self._model = None
        self._feature_cols: List[str] = list(FEATURE_COLUMNS)
        self._init_model()

    def _init_model(self) -> None:
        try:
            import lightgbm as lgb
        except ImportError as e:
            raise RuntimeError(
                "lightgbm is required for OnlineLearner. pip install lightgbm"
            ) from e
        self._lgb = lgb
        self._params = {
            "objective": "regression",
            "metric": "rmse",
            "num_leaves": 15,
            "learning_rate": 0.05,
            "feature_fraction": 0.8,
            "bagging_fraction": 0.8,
            "bagging_freq": 5,
            "min_data_in_leaf": 20,
            "verbose": -1,
        }
        if self.model_path.exists():
            try:
                self._model = lgb.Booster(model_file=str(self.model_path))
                logger.info("Loaded existing model from %s", self.model_path)
            except Exception as e:
                logger.warning("Failed to load model: %s; starting fresh", e)
                self._model = None

    def fit(self, df: pd.DataFrame, num_boost_round: int = 200) -> None:
        """Train from scratch."""
        X, y = self._xy(df)
        if len(X) < 20:
            logger.warning("OnlineLearner.fit: only %d rows; skipping", len(X))
            return
        train_data = self._lgb.Dataset(X, label=y, feature_name=self._feature_cols)
        self._model = self._lgb.train(
            self._params, train_data, num_boost_round=num_boost_round
        )
        self.save()

    def partial_fit(self, df: pd.DataFrame, num_boost_round: int = 50) -> None:
        """Warm-start retrain on new data."""
        if self._model is None:
            return self.fit(df)
        X, y = self._xy(df)
        if len(X) < 5:
            return
        train_data = self._lgb.Dataset(X, label=y, feature_name=self._feature_cols)
        self._model = self._lgb.train(
            self._params, train_data, num_boost_round=num_boost_round,
            init_model=self._model,
        )
        self.save()

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        if self._model is None:
            return np.zeros(len(df))
        X, _ = self._xy(df, with_y=False)
        return self._model.predict(X)

    def per_strategy_expected_pnl(self, df: pd.DataFrame) -> dict:
        """Return {strategy_id: mean_predicted_pnl} over the input rows."""
        if df.empty or self._model is None or "strategy_id" not in df.columns:
            return {}
        out = {}
        for sid, group in df.groupby("strategy_id"):
            preds = self.predict(group)
            out[str(sid)] = float(np.mean(preds))
        return out

    def feature_importance(self) -> dict:
        if self._model is None:
            return {}
        imp = self._model.feature_importance(importance_type="gain")
        return {name: float(v) for name, v in zip(self._feature_cols, imp)}

    def save(self) -> str:
        if self._model is not None:
            self._model.save_model(str(self.model_path))
        return str(self.model_path)

    def load(self, path: Optional[str] = None) -> None:
        p = Path(path) if path else self.model_path
        if p.exists():
            self._model = self._lgb.Booster(model_file=str(p))

    def _xy(self, df: pd.DataFrame, with_y: bool = True):
        for c in self._feature_cols:
            if c not in df.columns:
                df[c] = float("nan")
        X = df[self._feature_cols].astype(float).fillna(0.0)
        if with_y:
            y = df[LABEL_COLUMN].astype(float).values if LABEL_COLUMN in df.columns else None
            return X, y
        return X, None
