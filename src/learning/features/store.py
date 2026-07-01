"""Feature store — materialize a feature vector for (symbol, ts, strategy).

Reads from:
- Yahoo price/volume (via yfinance Ticker)
- Cached sentiment scores (data/sentiment_cache.db)
- Regime detector (src/learning/regime.py)
- Strategy prior performance (data/cycles.json + closed trades)

Returns a dict keyed by schema.FEATURE_COLUMNS + IDENTITY_COLUMNS.
Missing data → NaN. Never raises.
"""
from __future__ import annotations
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd

from src.learning.features.schema import FEATURE_COLUMNS, IDENTITY_COLUMNS

logger = logging.getLogger(__name__)


class FeatureStore:
    def __init__(self) -> None:
        self._yf = None  # lazy
        self._regime = None  # lazy

    def _yahoo(self):
        if self._yf is None:
            import yfinance as yf
            self._yf = yf
        return self._yf

    def materialize(
        self, symbol: str, strategy_id: str, ts: Optional[datetime] = None
    ) -> Dict[str, Any]:
        ts = ts or datetime.now(timezone.utc)
        row: Dict[str, Any] = {c: float("nan") for c in FEATURE_COLUMNS}
        for c in IDENTITY_COLUMNS:
            row[c] = None
        row["ts"] = ts.isoformat()
        row["symbol"] = symbol
        row["strategy_id"] = strategy_id
        row["hour_of_day"] = ts.hour
        row["day_of_week"] = ts.weekday()

        # Price + volume + returns from yfinance
        try:
            yf = self._yahoo()
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="60d", interval="1h", auto_adjust=False)
            if hist is not None and not hist.empty and len(hist) >= 2:
                closes = hist["Close"].astype(float)
                volumes = hist["Volume"].astype(float)
                row["price"] = float(closes.iloc[-1])
                row["volume"] = float(volumes.iloc[-1])
                # returns
                for h, key in [(1, "returns_1h"), (4, "returns_4h"),
                               (24, "returns_1d"), (120, "returns_5d")]:
                    if len(closes) > h:
                        prev = float(closes.iloc[-1 - h])
                        if prev > 0:
                            row[key] = (row["price"] - prev) / prev
                # realized vol (std of 1h returns)
                if len(closes) > 24:
                    rets = closes.pct_change().dropna()
                    row["realized_vol_1d"] = float(rets.tail(24).std() * math.sqrt(24))
                if len(closes) > 120:
                    rets = closes.pct_change().dropna()
                    row["realized_vol_5d"] = float(rets.tail(120).std() * math.sqrt(24))
                # volume z-score
                if len(volumes) >= 20:
                    mu = float(volumes.tail(20).mean())
                    sd = float(volumes.tail(20).std())
                    if sd > 0:
                        row["volume_zscore_20d"] = (row["volume"] - mu) / sd
                # 1-day volume change
                if len(volumes) > 24:
                    prev_v = float(volumes.iloc[-1 - 24])
                    if prev_v > 0:
                        row["volume_pct_change_1d"] = (row["volume"] - prev_v) / prev_v
        except Exception as e:
            logger.warning("FeatureStore yahoo %s: %s", symbol, e)

        # Technical indicators (simple SMA/RSI inline to avoid extra deps)
        try:
            if "price" in row and not math.isnan(row["price"]):
                closes = self._yahoo().Ticker(symbol).history(
                    period="60d", interval="1h", auto_adjust=False
                )["Close"].astype(float)
                if len(closes) >= 14:
                    row["rsi_14"] = self._rsi(closes, 14)
                if len(closes) >= 26:
                    row["macd_signal"] = self._macd_signal(closes)
                if len(closes) >= 20:
                    row["bb_position"] = self._bb_position(closes, 20)
                if len(closes) >= 14:
                    row["atr_14"] = self._atr(closes, 14)
                if len(closes) >= 14:
                    row["adx_14"] = self._adx(closes, 14)
        except Exception as e:
            logger.warning("FeatureStore indicators %s: %s", symbol, e)

        # Sentiment (read from sentiment cache if present)
        try:
            from src.sentiment.collector import latest_sentiment
            s = latest_sentiment(symbol)
            if s is not None:
                row["sentiment_score"] = float(s.get("score", float("nan")))
                row["sentiment_change_1d"] = float(s.get("change_1d", float("nan")))
                row["news_count_24h"] = float(s.get("count_24h", 0))
        except Exception as e:
            logger.debug("sentiment for %s unavailable: %s", symbol, e)

        # Regime
        try:
            from src.learning.regime import current_regime
            r = current_regime(symbol)
            if r is not None:
                row["regime_bull"] = 1.0 if r.get("regime") == "bull" else 0.0
                row["regime_bear"] = 1.0 if r.get("regime") == "bear" else 0.0
                row["regime_sideways"] = 1.0 if r.get("regime") == "sideways" else 0.0
                row["regime_confidence"] = float(r.get("confidence", float("nan")))
        except Exception as e:
            logger.debug("regime for %s unavailable: %s", symbol, e)

        # Prior performance (placeholder — populated by labeling builder)
        # Initialized to neutral; the labeling pipeline fills these in for
        # the strategy/symbol pair based on rolling 30d closed trades.
        row["strategy_prior_sharpe_30d"] = 0.0
        row["strategy_prior_winrate_30d"] = 0.5
        row["strategy_prior_trade_count_30d"] = 0
        row["symbol_prior_realized_vol_30d"] = row.get("realized_vol_1d", float("nan"))
        row["symbol_prior_avg_pnl_30d"] = 0.0

        return row

    # ── Technical indicator helpers (kept inline to avoid extra deps) ──
    @staticmethod
    def _rsi(closes: pd.Series, period: int = 14) -> float:  # type: ignore[type-arg]
        deltas = closes.diff()
        gains = deltas.where(deltas > 0, 0.0)
        losses = -deltas.where(deltas < 0, 0.0)
        avg_gain = gains.rolling(period).mean().iloc[-1]
        avg_loss = losses.rolling(period).mean().iloc[-1]
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100 - (100 / (1 + rs)))

    @staticmethod
    def _macd_signal(closes: pd.Series) -> float:  # type: ignore[type-arg]
        ema12 = closes.ewm(span=12, adjust=False).mean()
        ema26 = closes.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        return float(macd.iloc[-1] - signal.iloc[-1])

    @staticmethod
    def _bb_position(closes: pd.Series, period: int = 20) -> float:  # type: ignore[type-arg]
        sma = closes.rolling(period).mean().iloc[-1]
        std = closes.rolling(period).std().iloc[-1]
        upper = sma + 2 * std
        lower = sma - 2 * std
        if upper == lower:
            return 0.5
        return float((closes.iloc[-1] - lower) / (upper - lower))

    @staticmethod
    def _atr(closes: pd.Series, period: int = 14) -> float:  # type: ignore[type-arg]
        # Simplified: uses close-to-close changes as a proxy
        tr = closes.diff().abs()
        return float(tr.rolling(period).mean().iloc[-1])

    @staticmethod
    def _adx(closes: pd.Series, period: int = 14) -> float:  # type: ignore[type-arg]
        # Very rough ADX proxy: normalized absolute returns over period
        rets = closes.pct_change().abs()
        return float(rets.rolling(period).mean().iloc[-1] * 100)
