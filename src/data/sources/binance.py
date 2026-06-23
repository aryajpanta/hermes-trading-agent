"""Binance data source implementation.

Public REST API (no auth required for market data). Returns real OHLCV
candles for crypto pairs. Used as the primary crypto source for the
unified trading system; CoinGecko remains a fallback.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

from src.data.models import DataSource, MarketData
from src.data.sources.base import BaseDataSource

logger = logging.getLogger(__name__)

BINANCE_BASE_URL = "https://api.binance.com/api/v3"

# Map common symbols to Binance trading pairs (USDT-quoted)
BINANCE_SYMBOL_MAP: Dict[str, str] = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",
    "DOGE": "DOGEUSDT",
    "AVAX": "AVAXUSDT",
    "MATIC": "MATICUSDT",
    "DOT": "DOTUSDT",
    "LINK": "LINKUSDT",
    "LTC": "LTCUSDT",
}

# Binance interval -> milliseconds
INTERVAL_MS: Dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


class BinanceSource(BaseDataSource):
    """Binance public REST API for crypto OHLCV."""

    def __init__(
        self,
        rate_limit_requests: int = 1200,
        rate_limit_window: int = 60,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize Binance source.

        Args:
            rate_limit_requests: Max requests per window (Binance: 1200/min).
            rate_limit_window: Time window in seconds.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry attempts.
        """
        super().__init__(
            source_name=DataSource.BINANCE,
            rate_limit_requests=rate_limit_requests,
            rate_limit_window=rate_limit_window,
            timeout=timeout,
            max_retries=max_retries,
        )
        self._session = requests.Session()

    def _to_pair(self, symbol: str) -> str:
        """Map a symbol like 'BTC' to 'BTCUSDT'."""
        return BINANCE_SYMBOL_MAP.get(symbol.upper(), f"{symbol.upper()}USDT")

    def _parse_interval(self, interval: str) -> str:
        """Normalize an interval to Binance format."""
        return interval if interval in INTERVAL_MS else "1d"

    def _parse_period_ms(self, period: str) -> int:
        """Convert a period string like '1y'/'30d' to milliseconds."""
        days = self.parse_period(period)
        return days * 86_400_000

    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> List[MarketData]:
        """Fetch OHLCV candles from Binance.

        Args:
            symbol: Crypto symbol (e.g., 'BTC', 'ETH', 'SOL').
            period: Period like '1y', '90d', '30d'.
            interval: Binance interval (1m, 5m, 15m, 1h, 4h, 1d, 1w).

        Returns:
            List of MarketData records.
        """
        pair = self._to_pair(symbol)
        bi = self._parse_interval(interval)
        lookback_ms = self._parse_period_ms(period)
        end_ms = int(datetime.utcnow().timestamp() * 1000)
        start_ms = end_ms - lookback_ms

        def _fetch() -> List[MarketData]:
            url = f"{BINANCE_BASE_URL}/klines"
            params: Dict[str, Any] = {
                "symbol": pair,
                "interval": bi,
                "startTime": start_ms,
                "endTime": end_ms,
                "limit": 1000,
            }
            response = self._session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            rows = response.json()
            if not rows:
                logger.warning(f"No kline data returned for {pair} from Binance")
                return []

            records: List[MarketData] = []
            for row in rows:
                # Binance kline format:
                # [open_time, open, high, low, close, volume, close_time, ...]
                ts_ms = int(row[0])
                records.append(
                    MarketData(
                        symbol=symbol.upper(),
                        timestamp=datetime.utcfromtimestamp(ts_ms / 1000),
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=int(float(row[5])),
                        source=DataSource.BINANCE,
                        metadata={"pair": pair, "interval": bi},
                    )
                )

            logger.info(
                f"Fetched {len(records)} {bi} candles for {symbol} from Binance"
            )
            return records

        return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]

    def fetch_price(self, symbol: str) -> Optional[float]:
        """Fetch current spot price for a symbol.

        Args:
            symbol: Crypto symbol (e.g., 'BTC').

        Returns:
            Current price in USDT, or None on error.
        """
        pair = self._to_pair(symbol)

        def _fetch() -> Optional[float]:
            url = f"{BINANCE_BASE_URL}/ticker/price"
            response = self._session.get(
                url, params={"symbol": pair}, timeout=self.timeout
            )
            response.raise_for_status()
            data = response.json()
            return float(data["price"]) if "price" in data else None

        try:
            return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Binance fetch_price({symbol}) failed: {e}")
            return None

    def fetch_prices(self, symbols: List[str]) -> Dict[str, Optional[float]]:
        """Fetch prices for multiple symbols in one call (uses /ticker/price).

        Args:
            symbols: List of symbols like ['BTC','ETH','SOL'].

        Returns:
            Mapping of symbol -> price (or None on error).
        """
        out: Dict[str, Optional[float]] = {s: None for s in symbols}
        # Build pairs as a JSON array for the symbols param
        import json as _json

        pairs = [self._to_pair(s) for s in symbols]

        def _fetch() -> List[Dict[str, Any]]:
            url = f"{BINANCE_BASE_URL}/ticker/price"
            response = self._session.get(
                url,
                params={"symbols": _json.dumps(pairs)},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()

        try:
            rows = self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]
            pair_to_sym = {self._to_pair(s): s for s in symbols}
            for row in rows:
                sym = pair_to_sym.get(row["symbol"])
                if sym:
                    out[sym] = float(row["price"])
        except Exception as e:
            logger.error(f"Binance fetch_prices failed: {e}")

        return out

    def fetch_24h(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch 24h ticker stats for a symbol.

        Returns dict with lastPrice, priceChangePercent, volume, etc.
        """
        pair = self._to_pair(symbol)

        def _fetch() -> Dict[str, Any]:
            url = f"{BINANCE_BASE_URL}/ticker/24hr"
            response = self._session.get(
                url, params={"symbol": pair}, timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()

        try:
            return self._retry_with_backoff(_fetch)  # type: ignore[no-any-return]
        except Exception as e:
            logger.error(f"Binance fetch_24h({symbol}) failed: {e}")
            return None

    def is_available(self) -> bool:
        """Check if Binance API is reachable."""
        try:
            response = self._session.get(
                f"{BINANCE_BASE_URL}/ping", timeout=5
            )
            return response.status_code == 200
        except Exception:
            return False
