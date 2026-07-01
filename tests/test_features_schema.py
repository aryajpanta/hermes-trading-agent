"""Tests for the feature schema."""
from src.learning.features.schema import (
    FEATURE_COLUMNS, LABEL_COLUMN, IDENTITY_COLUMNS, ALL_COLUMNS,
    LABEL_HORIZON_HOURS,
)


def test_feature_schema_has_required_columns():
    required = [
        "price", "returns_1h", "returns_1d", "volume", "volume_zscore_20d",
        "rsi_14", "macd_signal", "bb_position", "atr_14",
        "sentiment_score", "news_count_24h",
        "regime_bull", "regime_bear", "regime_sideways",
        "strategy_prior_sharpe_30d", "strategy_prior_winrate_30d",
        "symbol_prior_realized_vol_30d",
    ]
    missing = [c for c in required if c not in FEATURE_COLUMNS]
    assert not missing, f"missing required feature columns: {missing}"


def test_label_column_is_pnl_pct():
    assert LABEL_COLUMN == "realized_pnl_pct"


def test_identity_columns_present():
    assert "ts" in IDENTITY_COLUMNS
    assert "symbol" in IDENTITY_COLUMNS
    assert "strategy_id" in IDENTITY_COLUMNS


def test_all_columns_includes_identity_features_label():
    for c in IDENTITY_COLUMNS:
        assert c in ALL_COLUMNS
    for c in FEATURE_COLUMNS:
        assert c in ALL_COLUMNS
    assert LABEL_COLUMN in ALL_COLUMNS


def test_label_horizon_is_positive():
    assert LABEL_HORIZON_HOURS > 0
    assert LABEL_HORIZON_HOURS <= 168  # at most a week
