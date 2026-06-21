"""Base class for market data sources.

All data sources implement a common interface with rate limiting,
retry logic, and error handling.
"""

import time
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Optional

from src.data.models import DataSource, MarketData

logger = logging.getLogger(__name__)


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, max_requests: int, time_window_seconds: int) -> None:
        """Initialize rate limiter.

        Args:
            max_requests: Maximum requests allowed in the time window.
            time_window_seconds: Duration of the time window in seconds.
        """
        self.max_requests = max_requests
        self.time_window_seconds = time_window_seconds
        self._timestamps: List[float] = []

    def wait_if_needed(self) -> float:
        """Wait if rate limit would be exceeded. Returns wait time in seconds."""
        now = time.time()
        # Remove timestamps outside the window
        self._timestamps = [
            t for t in self._timestamps
            if now - t < self.time_window_seconds
        ]

        if len(self._timestamps) >= self.max_requests:
            # Need to wait until oldest request falls outside window
            wait_time = self.time_window_seconds - (now - self._timestamps[0])
            if wait_time > 0:
                logger.debug(f"Rate limit: waiting {wait_time:.1f}s")
                time.sleep(wait_time)
                now = time.time()
                # Re-clean after waiting
                self._timestamps = [
                    t for t in self._timestamps
                    if now - t < self.time_window_seconds
                ]

        self._timestamps.append(time.time())
        return 0.0

    @property
    def remaining_quota(self) -> int:
        """Remaining requests in current window."""
        now = time.time()
        self._timestamps = [
            t for t in self._timestamps
            if now - t < self.time_window_seconds
        ]
        return max(0, self.max_requests - len(self._timestamps))


class BaseDataSource(ABC):
    """Abstract base class for market data sources."""

    def __init__(
        self,
        source_name: DataSource,
        rate_limit_requests: int = 100,
        rate_limit_window: int = 60,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        """Initialize the data source.

        Args:
            source_name: Identifier for this data source.
            rate_limit_requests: Max requests per time window.
            rate_limit_window: Time window in seconds.
            timeout: Request timeout in seconds.
            max_retries: Maximum number of retries on failure.
        """
        self.source_name = source_name
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = RateLimiter(rate_limit_requests, rate_limit_window)
        self._retry_count = 0

    def _retry_with_backoff(self, func, *args, **kwargs):  # type: ignore[no-untyped-def]
        """Execute a function with exponential backoff retry logic.

        Args:
            func: Function to execute.
            *args: Positional arguments for the function.
            **kwargs: Keyword arguments for the function.

        Returns:
            Result of the function call.

        Raises:
            Exception: If all retries are exhausted.
        """
        import requests

        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                self.rate_limiter.wait_if_needed()
                return func(*args, **kwargs)
            except requests.exceptions.HTTPError as e:
                last_error = e
                if e.response is not None and e.response.status_code == 429:
                    # Rate limited - use longer backoff
                    wait_time = (2 ** attempt) * 5
                    logger.warning(
                        f"Rate limited by {self.source_name.value}, "
                        f"waiting {wait_time}s (attempt {attempt + 1})"
                    )
                    time.sleep(wait_time)
                elif e.response is not None and 500 <= e.response.status_code < 600:
                    # Server error - retry with backoff
                    wait_time = (2 ** attempt) * 2
                    logger.warning(
                        f"Server error from {self.source_name.value}: {e.response.status_code}, "
                        f"retrying in {wait_time}s (attempt {attempt + 1})"
                    )
                    time.sleep(wait_time)
                else:
                    # Client error (not 429) - don't retry
                    raise
            except requests.exceptions.ConnectionError as e:
                last_error = e
                wait_time = (2 ** attempt) * 2
                logger.warning(
                    f"Connection error with {self.source_name.value}, "
                    f"retrying in {wait_time}s (attempt {attempt + 1})"
                )
                time.sleep(wait_time)
            except requests.exceptions.Timeout as e:
                last_error = e
                wait_time = (2 ** attempt) * 2
                logger.warning(
                    f"Timeout from {self.source_name.value}, "
                    f"retrying in {wait_time}s (attempt {attempt + 1})"
                )
                time.sleep(wait_time)

        raise Exception(
            f"All {self.max_retries + 1} attempts failed for {self.source_name.value}: {last_error}"
        )

    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        period: str = "1y",
        interval: str = "1d",
    ) -> List[MarketData]:
        """Fetch OHLCV data for a symbol.

        Args:
            symbol: Ticker symbol to fetch.
            period: Period to fetch (e.g., '1y', '6mo', '30d').
            interval: Data interval (e.g., '1d', '1h', '5m').

        Returns:
            List of MarketData records.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this data source is currently available."""
        ...

    @staticmethod
    def parse_period(period: str) -> int:
        """Parse a period string into days.

        Args:
            period: Period string like '1y', '6mo', '30d', '1w'.

        Returns:
            Number of days.
        """
        period = period.lower().strip()

        multipliers = {
            "y": 365,
            "mo": 30,
            "w": 7,
            "d": 1,
        }

        for suffix, multiplier in multipliers.items():
            if period.endswith(suffix):
                try:
                    value = int(period[: -len(suffix)])
                    return value * multiplier
                except ValueError:
                    continue

        # Default to 1 year
        return 365
