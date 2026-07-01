"""Single source of truth for the feature vector schema.

Every feature is a column. Order matters for parquet/numpy alignment.
Numeric features only (categoricals like regime get one-hot downstream).
"""
from __future__ import annotations
from typing import List

# Identity columns (passed through but not used as features)
IDENTITY_COLUMNS: List[str] = ["ts", "symbol", "strategy_id"]

# Feature columns (numeric, model-input)
FEATURE_COLUMNS: List[str] = [
    # Price-based
    "price",
    "returns_1h", "returns_4h", "returns_1d", "returns_5d",
    "realized_vol_1d", "realized_vol_5d",
    # Volume
    "volume", "volume_zscore_20d", "volume_pct_change_1d",
    # Technical
    "rsi_14", "macd_signal", "bb_position", "atr_14", "adx_14",
    # Sentiment & news
    "sentiment_score", "sentiment_change_1d", "news_count_24h",
    "news_sentiment_volume_24h",
    # Regime (numeric: 0=sideways, 1=bull, 2=bear; categorical handled separately)
    "regime_bull", "regime_bear", "regime_sideways",
    "regime_confidence",
    # Prior performance (per-strategy, per-symbol)
    "strategy_prior_sharpe_30d",
    "strategy_prior_winrate_30d",
    "strategy_prior_trade_count_30d",
    "symbol_prior_realized_vol_30d",
    "symbol_prior_avg_pnl_30d",
    # Time
    "hour_of_day", "day_of_week",
]

LABEL_COLUMN: str = "realized_pnl_pct"
LABEL_HORIZON_HOURS: int = 24  # how long we hold to realize the label

ALL_COLUMNS: List[str] = IDENTITY_COLUMNS + FEATURE_COLUMNS + [LABEL_COLUMN]
