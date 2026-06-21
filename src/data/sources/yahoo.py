"""Yahoo Finance data source implementation.

Uses yfinance library to fetch OHLCV data for stocks, ETFs,
forex pairs, and commodities from Yahoo Finance.
"""

import logging
from datetime import datetime
from typing import List, Optional

import yfinance as yf

from src.data.models import COINGECKO_MAP, YAHOO_SYMBOL_MAP, DataSource, MarketData
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)


class YahooFinanceSource(BaseDataSource):
    """Yahoo Finance data source using yfinance library."""

    def __init__(
        self,
        rate_limit_requests: int = 2000,
        rate_limit_window: int = 3600,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize Yahoo Finance source.

        Args:
            rate_limit_requests: Max requests per window (default: 2000/hr).
            rate_limit_window: Time window in seconds (default: 3600 = 1hr).
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts.
        """
        super().__init__(
            source_name=DataSource.YAHOO,
            rate_limit_requests=rate_limit_requests,
            rate_limit_window=rate_limit_window,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _normalize_symbol(self, symbol: str) -> str:
        """Normalize a symbol for Yahoo Finance.

        Converts standard symbols to Yahoo Finance format.
        """
        # Check explicit mapping first
        if symbol in YAHOO_SYMBOL_MAP:
            return YAHOO_SYMBOL_MAP[symbol]

        # Crypto symbols: BTC -> BTC-USD
        if symbol in COINGECKO_MAP:
            return f"{symbol}-USD"

        # Forex: EUR-USD -> EURUSD=X
        if "-" in symbol and len(symbol) == 7:
            parts = symbol.split("-")
            if len(parts) == 2 and len(parts[0]) == 3 and len(parts[1]) == 3:
                return f"{parts[0]}{parts[1]}=X"

        return symbol

    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> List[MarketData]:
        """Fetch OHLCV data from Yahoo Finance.

        Args:
            symbol: Ticker symbol.
            period: Period to fetch (e.g., '1y', '6mo', '30d').
            interval: Data interval (e.g., '1d', '1h').

        Returns:
            List of MarketData records.
        """
        yahoo_symbol = self._normalize_symbol(symbol)

        def _fetch() -> List[MarketData]:
            ticker = yf.Ticker(yahoo_symbol)
            df = ticker.history(period=period, interval=interval)

            if df.empty:
                logger.warning(f"No data returned for {symbol} (Yahoo: {yahoo_symbol})")
                return []

            records: List[MarketData] = []
            for idx, row in df.iterrows():
                try:
                    timestamp = idx.to_pydatetime()
                    # Make timezone-naive if needed
                    if hasattr(timestamp, "tzinfo") and timestamp.tzinfo is not None:
                        timestamp = timestamp.replace(tzinfo=None)

                    record = MarketData(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                        source=DataSource.YAHOO,
                        metadata={
                            "yahoo_symbol": yahoo_symbol,
                            "dividends": float(row.get("Dividends", 0)),
                            "stock_splits": float(row.get("Stock Splits", 0)),
                        },
                    )
                    records.append(record)
                except (ValueError, KeyError) as e:
                    logger.debug(f"Skipping row for {symbol}: {e}")
                    continue

            logger.info(f"Fetched {len(records)} records for {symbol} from Yahoo Finance")
            return records

        return self._retry_with_backoff(_fetch)

    def is_available(self) -> bool:
        """Check if Yahoo Finance is available."""
        try:
            ticker = yf.Ticker("AAPL")
            info = ticker.fast_info
            return info is not None
        except Exception:
            return False

    def get_ticker_info(self, symbol: str) -> Optional[dict]:
        """Get additional ticker information.

        Args:
            symbol: Ticker symbol.

        Returns:
            Dictionary with ticker info or None.
        """
        yahoo_symbol = self._normalize_symbol(symbol)
        try:
            ticker = yf.Ticker(yahoo_symbol)
            return ticker.fast_info
        except Exception as e:
            logger.error(f"Failed to get info for {symbol}: {e}")
            return None
