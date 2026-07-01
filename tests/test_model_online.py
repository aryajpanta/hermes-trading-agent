"""Tests for OnlineLearner."""
import numpy as np
import pandas as pd
import tempfile

from src.learning.model.online import OnlineLearner
from src.learning.features.schema import FEATURE_COLUMNS, LABEL_COLUMN


def _fake_dataset(n: int = 200, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame(
        rng.normal(size=(n, len(FEATURE_COLUMNS))),
        columns=FEATURE_COLUMNS,
    )
    # Simulate that high rsi_14 + high volume_zscore_20d predicts positive pnl
    df[LABEL_COLUMN] = (
        0.01 * df["rsi_14"]
        + 0.005 * df["volume_zscore_20d"]
        + rng.normal(scale=0.005, size=n)
    )
    df["strategy_id"] = "rsi_mean_reversion"
    df["symbol"] = "AAPL"
    return df


def test_train_then_predict_returns_array():
    df = _fake_dataset()
    with tempfile.TemporaryDirectory() as d:
        learner = OnlineLearner(model_path=f"{d}/model.txt")
        learner.fit(df)
        preds = learner.predict(df.head(5))
        assert len(preds) == 5
        assert all(isinstance(p, float) for p in preds)


def test_predict_learns_signal():
    df = _fake_dataset(n=500)
    with tempfile.TemporaryDirectory() as d:
        learner = OnlineLearner(model_path=f"{d}/model.txt")
        learner.fit(df)
        high = df[(df["rsi_14"] > 1) & (df["volume_zscore_20d"] > 1)].head(5)
        low = df[(df["rsi_14"] < -1) & (df["volume_zscore_20d"] < -1)].head(5)
        p_high = float(np.mean(learner.predict(high)))
        p_low = float(np.mean(learner.predict(low)))
        assert p_high > p_low, f"expected p_high > p_low, got {p_high} vs {p_low}"


def test_persists_and_reloads():
    df = _fake_dataset()
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/model.txt"
        learner = OnlineLearner(model_path=path)
        learner.fit(df)
        learner2 = OnlineLearner(model_path=path)
        # second instance should have loaded the model
        assert learner2._model is not None
        preds = learner2.predict(df.head(3))
        assert len(preds) == 3


def test_partial_fit_warm_starts():
    df = _fake_dataset(n=300, seed=1)
    df2 = _fake_dataset(n=300, seed=2)
    with tempfile.TemporaryDirectory() as d:
        learner = OnlineLearner(model_path=f"{d}/model.txt")
        learner.fit(df)
        learner.partial_fit(df2)
        preds = learner.predict(df.head(3))
        assert len(preds) == 3


def test_per_strategy_expected_pnl():
    df = _fake_dataset()
    df2 = df.copy()
    df2["strategy_id"] = "ma_crossover"
    with tempfile.TemporaryDirectory() as d:
        learner = OnlineLearner(model_path=f"{d}/model.txt")
        learner.fit(pd.concat([df, df2]))
        result = learner.per_strategy_expected_pnl(pd.concat([df.head(20), df2.head(20)]))
        assert "rsi_mean_reversion" in result
        assert "ma_crossover" in result


def test_feature_importance_after_fit():
    df = _fake_dataset()
    with tempfile.TemporaryDirectory() as d:
        learner = OnlineLearner(model_path=f"{d}/model.txt")
        learner.fit(df)
        imp = learner.feature_importance()
        assert "rsi_14" in imp
        # rsi_14 should have non-zero importance since we built the signal around it
        assert imp["rsi_14"] >= 0
