"""Volume/flow data source.

Equity volume: yfinance (already in HTA deps).
Crypto volume: yfinance `SYMBOL-USD` (Binance blocked from US IPs per memory).
Falls back to empty DataFrame on any error (callers handle missing data).
"""
from __future__ import annotations
import logging
from typing import Optional
import pandas as pd

logger = logging.getLogger(__name__)


class VolumeSource:
    """Pulls volume/OHLCV bars. Delegates to yfinance."""

    def __init__(self) -> None:
        import yfinance as yf
        self._yf = yf

    def get_volume(
        self, symbol: str, period: str = "30d", interval: str = "1h"
    ) -> pd.DataFrame:
        """Return OHLCV DataFrame. Empty DataFrame on failure."""
        try:
            t = self._yf.Ticker(symbol)
            df = t.history(period=period, interval=interval, auto_adjust=False)
            if df is None or df.empty:
                return pd.DataFrame(
                    {"open": [], "high": [], "low": [], "close": [], "volume": []}
                )
            return df[["Open", "High", "Low", "Close", "Volume"]].rename(
                columns={"Open": "open", "High": "high", "Low": "low",
                         "Close": "close", "Volume": "volume"}
            )
        except Exception as e:
            logger.warning("VolumeSource %s failed: %s", symbol, e)
            return pd.DataFrame(
                {"open": [], "high": [], "low": [], "close": [], "volume": []}
            )
