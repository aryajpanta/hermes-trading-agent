"""Alpha Vantage data source implementation.

Uses the Alpha Vantage API for stock and forex data.
Free tier: 25 requests per day, 5 requests per minute.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

from src.data.models import DataSource, MarketData
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

ALPHA_VANTAGE_BASE_URL = "https://www.alphavantage.co/query"


class AlphaVantageSource(BaseDataSource):
    """Alpha Vantage data source for stock and forex data."""

    def __init__(
        self,
        api_key: str = "",
        rate_limit_requests: int = 5,
        rate_limit_window: int = 60,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize Alpha Vantage source.

        Args:
            api_key: Alpha Vantage API key (required for production use).
            rate_limit_requests: Max requests per minute (default: 5).
            rate_limit_window: Time window in seconds (default: 60).
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts.
        """
        super().__init__(
            source_name=DataSource.ALPHA_VANTAGE,
            rate_limit_requests=rate_limit_requests,
            rate_limit_window=rate_limit_window,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.api_key = api_key
        self._session = requests.Session()

    def _is_forex_pair(self, symbol: str) -> bool:
        """Check if symbol represents a forex pair."""
        return (
            "-" in symbol
            and len(symbol) == 7
            and symbol[:3].isalpha()
            and symbol[4:].isalpha()
        )

    def _parse_forex_pair(self, symbol: str) -> tuple[str, str]:
        """Parse a forex pair like 'EUR-USD' into ('EUR', 'USD')."""
        parts = symbol.split("-")
        return parts[0], parts[1]

    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> List[MarketData]:
        """Fetch OHLCV data from Alpha Vantage.

        Args:
            symbol: Ticker symbol or forex pair.
            period: Period to fetch (used to calculate outputsize).
            interval: Data interval (supports: 1min, 5min, 15min, 30min, 60min, daily).

        Returns:
            List of MarketData records.
        """
        if not self.api_key:
            logger.warning("Alpha Vantage API key not set, skipping")
            return []

        def _fetch() -> List[MarketData]:
            days = self.parse_period(period)
            outputsize = "full" if days > 100 else "compact"

            if self._is_forex_pair(symbol):
                return self._fetch_forex(symbol, outputsize)
            else:
                return self._fetch_stock(symbol, outputsize)

        return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]

    def _fetch_stock(
        self, symbol: str, outputsize: str = "full"
    ) -> List[MarketData]:
        """Fetch stock data from Alpha Vantage."""
        params: Dict[str, Any] = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "apikey": self.api_key,
            "outputsize": outputsize,
        }

        response = self._session.get(
            ALPHA_VANTAGE_BASE_URL, params=params, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()

        # Check for API errors
        if "Error Message" in data:
            raise ValueError(f"Alpha Vantage API error: {data['Error Message']}")
        if "Note" in data:
            logger.warning(f"Alpha Vantage rate limit note: {data['Note']}")
            raise Exception("Rate limit exceeded")

        time_series = data.get("Time Series (Daily)", {})
        if not time_series:
            logger.warning(f"No data returned for {symbol} from Alpha Vantage")
            return []

        records: List[MarketData] = []
        for date_str, values in time_series.items():
            try:
                timestamp = datetime.strptime(date_str, "%Y-%m-%d")
                record = MarketData(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=float(values["1. open"]),
                    high=float(values["2. high"]),
                    low=float(values["3. low"]),
                    close=float(values["4. close"]),
                    volume=int(values["5. volume"]),
                    source=DataSource.ALPHA_VANTAGE,
                    metadata={"alpha_vantage_function": "TIME_SERIES_DAILY"},
                )
                records.append(record)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping row for {symbol}: {e}")
                continue

        logger.info(
            f"Fetched {len(records)} records for {symbol} from Alpha Vantage"
        )
        return records

    def _fetch_forex(
        self, symbol: str, outputsize: str = "full"
    ) -> List[MarketData]:
        """Fetch forex data from Alpha Vantage."""
        from_symbol, to_symbol = self._parse_forex_pair(symbol)

        params: Dict[str, Any] = {
            "function": "FX_DAILY",
            "from_symbol": from_symbol,
            "to_symbol": to_symbol,
            "apikey": self.api_key,
            "outputsize": outputsize,
        }

        response = self._session.get(
            ALPHA_VANTAGE_BASE_URL, params=params, timeout=self.timeout
        )
        response.raise_for_status()
        data = response.json()

        if "Error Message" in data:
            raise ValueError(f"Alpha Vantage API error: {data['Error Message']}")
        if "Note" in data:
            logger.warning(f"Alpha Vantage rate limit note: {data['Note']}")
            raise Exception("Rate limit exceeded")

        time_series = data.get("Time Series FX (Daily)", {})
        if not time_series:
            logger.warning(f"No forex data returned for {symbol}")
            return []

        records: List[MarketData] = []
        for date_str, values in time_series.items():
            try:
                timestamp = datetime.strptime(date_str, "%Y-%m-%d")
                record = MarketData(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=float(values["1. open"]),
                    high=float(values["2. high"]),
                    low=float(values["3. low"]),
                    close=float(values["4. close"]),
                    volume=0,  # Forex doesn't have standard volume
                    source=DataSource.ALPHA_VANTAGE,
                    metadata={
                        "alpha_vantage_function": "FX_DAILY",
                        "from_symbol": from_symbol,
                        "to_symbol": to_symbol,
                    },
                )
                records.append(record)
            except (ValueError, KeyError) as e:
                logger.debug(f"Skipping forex row for {symbol}: {e}")
                continue

        logger.info(
            f"Fetched {len(records)} forex records for {symbol} from Alpha Vantage"
        )
        return records

    def is_available(self) -> bool:
        """Check if Alpha Vantage API is available."""
        if not self.api_key:
            return False
        try:
            params = {
                "function": "GLOBAL_QUOTE",
                "symbol": "AAPL",
                "apikey": self.api_key,
            }
            response = self._session.get(
                ALPHA_VANTAGE_BASE_URL, params=params, timeout=10
            )
            data = response.json()
            return "Global Quote" in data or "Note" in data
        except Exception:
            return False

    def get_intraday(
        self, symbol: str, interval: str = "5min", outputsize: str = "compact"
    ) -> List[MarketData]:
        """Get intraday data from Alpha Vantage.

        Args:
            symbol: Ticker symbol.
            interval: Time interval (1min, 5min, 15min, 30min, 60min).
            outputsize: 'compact' (last 100 points) or 'full'.

        Returns:
            List of MarketData records.
        """
        if not self.api_key:
            return []

        def _fetch() -> List[MarketData]:
            params: Dict[str, Any] = {
                "function": "TIME_SERIES_INTRADAY",
                "symbol": symbol,
                "interval": interval,
                "apikey": self.api_key,
                "outputsize": outputsize,
            }

            response = self._session.get(
                ALPHA_VANTAGE_BASE_URL, params=params, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()

            if "Error Message" in data:
                raise ValueError(f"Alpha Vantage API error: {data['Error Message']}")

            # Find the time series key
            time_series_key = f"Time Series ({interval})"
            time_series = data.get(time_series_key, {})

            records: List[MarketData] = []
            for datetime_str, values in time_series.items():
                try:
                    timestamp = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M:%S")
                    record = MarketData(
                        symbol=symbol,
                        timestamp=timestamp,
                        open=float(values["1. open"]),
                        high=float(values["2. high"]),
                        low=float(values["3. low"]),
                        close=float(values["4. close"]),
                        volume=int(values["5. volume"]),
                        source=DataSource.ALPHA_VANTAGE,
                        metadata={
                            "alpha_vantage_function": "TIME_SERIES_INTRADAY",
                            "interval": interval,
                        },
                    )
                    records.append(record)
                except (ValueError, KeyError) as e:
                    logger.debug(f"Skipping intraday row for {symbol}: {e}")
                    continue

            return records

        return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]
