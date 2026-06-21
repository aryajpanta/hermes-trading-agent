"""CoinGecko data source implementation.

Uses the CoinGecko free API to fetch cryptocurrency market data.
No API key required for free tier (10-30 requests/minute).
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from src.data.models import COINGECKO_MAP, DataSource, MarketData
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"


class CoinGeckoSource(BaseDataSource):
    """CoinGecko data source for cryptocurrency market data."""

    def __init__(
        self,
        api_key: str = "",
        rate_limit_requests: int = 10,
        rate_limit_window: int = 60,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize CoinGecko source.

        Args:
            api_key: CoinGecko API key (optional, for Pro tier).
            rate_limit_requests: Max requests per window (default: 10/min free).
            rate_limit_window: Time window in seconds.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts.
        """
        super().__init__(
            source_name=DataSource.COINGECKO,
            rate_limit_requests=rate_limit_requests,
            rate_limit_window=rate_limit_window,
            timeout=timeout,
            max_retries=max_retries,
        )
        self.api_key = api_key
        self._session = requests.Session()
        if api_key:
            self._session.headers["x-cg-demo-api-key"] = api_key

    def _get_coin_id(self, symbol: str) -> str:
        """Map a symbol to CoinGecko coin ID."""
        if symbol in COINGECKO_MAP:
            return COINGECKO_MAP[symbol]
        return symbol.lower()

    def _parse_period_days(self, period: str) -> int:
        """Parse period string to days for CoinGecko API."""
        period = period.lower().strip()
        multipliers = {"y": 365, "mo": 30, "w": 7, "d": 1}
        for suffix, mult in multipliers.items():
            if period.endswith(suffix):
                try:
                    return int(period[: -len(suffix)]) * mult
                except ValueError:
                    continue
        return 365

    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> List[MarketData]:
        """Fetch OHLCV data from CoinGecko.

        CoinGecko's /coins/{id}/ohlc endpoint returns candle data.
        For daily data, we use the /coins/{id}/market_chart endpoint.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC', 'ETH').
            period: Period to fetch.
            interval: Data interval (CoinGecko supports: daily by default).

        Returns:
            List of MarketData records.
        """
        coin_id = self._get_coin_id(symbol)
        days = self._parse_period_days(period)

        def _fetch() -> List[MarketData]:
            # Use market_chart for daily OHLCV data
            url = f"{COINGECKO_BASE_URL}/coins/{coin_id}/market_chart"
            params: Dict[str, Any] = {
                "vs_currency": "usd",
                "days": min(days, 365),  # Free tier max
                "interval": "daily",
            }

            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            prices = data.get("prices", [])
            volumes = data.get("total_volumes", [])
            market_caps = data.get("market_caps", [])

            if not prices:
                logger.warning(f"No price data returned for {symbol} from CoinGecko")
                return []

            records: List[MarketData] = []
            for i, price_point in enumerate(prices):
                timestamp_ms, close_price = price_point
                timestamp = datetime.utcfromtimestamp(timestamp_ms / 1000)

                # Get volume if available
                volume = 0
                if i < len(volumes):
                    volume = int(volumes[i][1])

                # CoinGecko doesn't provide true OHLC in market_chart,
                # so we approximate: open=close, high=close, low=close
                # For more accurate data, use the /ohlc endpoint
                record = MarketData(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=float(close_price),
                    high=float(close_price),
                    low=float(close_price),
                    close=float(close_price),
                    volume=volume,
                    source=DataSource.COINGECKO,
                    metadata={
                        "coin_id": coin_id,
                        "market_cap": float(market_caps[i][1])
                        if i < len(market_caps)
                        else 0,
                    },
                )
                records.append(record)

            logger.info(
                f"Fetched {len(records)} records for {symbol} from CoinGecko"
            )
            return records

        return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]

    def fetch_ohlc(
        self,
        symbol: str,
        days: int = 90,
    ) -> List[MarketData]:
        """Fetch true OHLC data using CoinGecko's OHLC endpoint.

        This provides actual open/high/low/close values but is limited
        to the last 90 days on the free tier.

        Args:
            symbol: Cryptocurrency symbol.
            days: Number of days (max 90 for free tier).

        Returns:
            List of MarketData records with true OHLC.
        """
        coin_id = self._get_coin_id(symbol)
        days = min(days, 90)  # Free tier limit

        def _fetch() -> List[MarketData]:
            url = f"{COINGECKO_BASE_URL}/coins/{coin_id}/ohlc"
            params = {"vs_currency": "usd", "days": days}

            response = self._session.get(url, params=params, timeout=self.timeout)  # type: ignore[arg-type]
            response.raise_for_status()
            data = response.json()

            if not data:
                logger.warning(f"No OHLC data returned for {symbol}")
                return []

            records: List[MarketData] = []
            for candle in data:
                timestamp_ms, open_price, high_price, low_price, close_price = candle
                timestamp = datetime.utcfromtimestamp(timestamp_ms / 1000)

                record = MarketData(
                    symbol=symbol,
                    timestamp=timestamp,
                    open=float(open_price),
                    high=float(high_price),
                    low=float(low_price),
                    close=float(close_price),
                    volume=0,  # OHLC endpoint doesn't provide volume
                    source=DataSource.COINGECKO,
                    metadata={"coin_id": coin_id, "ohlc_candle": True},
                )
                records.append(record)

            logger.info(
                f"Fetched {len(records)} OHLC records for {symbol} from CoinGecko"
            )
            return records

        return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]

    def is_available(self) -> bool:
        """Check if CoinGecko API is available."""
        try:
            url = f"{COINGECKO_BASE_URL}/ping"
            response = self._session.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_market_data(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get current market data for a cryptocurrency.

        Args:
            symbol: Cryptocurrency symbol.

        Returns:
            Dictionary with current market data or None.
        """
        coin_id = self._get_coin_id(symbol)
        try:
            url = f"{COINGECKO_BASE_URL}/coins/{coin_id}"
            params = {
                "localization": "false",
                "tickers": "false",
                "community_data": "false",
                "developer_data": "false",
            }
            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            market_data = data.get("market_data", {})
            return {
                "current_price": market_data.get("current_price", {}).get("usd", 0),
                "market_cap": market_data.get("market_cap", {}).get("usd", 0),
                "total_volume": market_data.get("total_volume", {}).get("usd", 0),
                "price_change_24h": market_data.get("price_change_24h", 0),
                "price_change_7d": market_data.get(
                    "price_change_percentage_7d", 0
                ),
                "price_change_30d": market_data.get(
                    "price_change_percentage_30d", 0
                ),
            }
        except Exception as e:
            logger.error(f"Failed to get market data for {symbol}: {e}")
            return None
