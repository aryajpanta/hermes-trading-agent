"""Market data collector - orchestrates data sources and storage.

This is the main entry point for collecting market data from
multiple sources and storing it in SQLite.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.data.models import (
    DEFAULT_COMMODITIES,
    DEFAULT_CRYPTO,
    DEFAULT_FOREX,
    DEFAULT_STOCKS,
    CollectionBatchResult,
    CollectionResult,
    DataSource,
    MarketData,
    Symbol,
    get_asset_type,
)
from src.data.sources.alphavantage import AlphaVantageSource
from src.data.sources.base import BaseDataSource
from src.data.sources.coingecko import CoinGeckoSource
from src.data.sources.yahoo import YahooFinanceSource
from src.data.storage import MarketDataStorage

logger = logging.getLogger(__name__)

# Mapping of symbols to their preferred data sources
SYMBOL_SOURCE_MAP: Dict[str, List[DataSource]] = {
    # Stocks - primarily Yahoo, Alpha Vantage as backup
    **{s: [DataSource.YAHOO, DataSource.ALPHA_VANTAGE] for s in DEFAULT_STOCKS},
    # Crypto - Binance primary (real OHLCV, no rate limits), CoinGecko + Yahoo as backup
    **{s: [DataSource.BINANCE, DataSource.COINGECKO, DataSource.YAHOO] for s in DEFAULT_CRYPTO},
    # Forex - Yahoo primary, Alpha Vantage as backup
    **{s: [DataSource.YAHOO, DataSource.ALPHA_VANTAGE] for s in DEFAULT_FOREX},
    # Commodities - Yahoo only
    **{s: [DataSource.YAHOO] for s in DEFAULT_COMMODITIES},
}


class MarketDataCollector:
    """Orchestrates market data collection from multiple sources.

    Manages data sources, handles fallback logic, and coordinates
    storage of collected data.
    """

    def __init__(
        self,
        storage_path: str = "data/market.db",
        yahoo_enabled: bool = True,
        coingecko_enabled: bool = True,
        alphavantage_enabled: bool = True,
        binance_enabled: bool = True,
        alphavantage_api_key: str = "",
        coingecko_api_key: str = "",
    ) -> None:
        """Initialize the collector.

        Args:
            storage_path: Path to SQLite database.
            yahoo_enabled: Enable Yahoo Finance source.
            coingecko_enabled: Enable CoinGecko source.
            alphavantage_enabled: Enable Alpha Vantage source.
            binance_enabled: Enable Binance source (crypto).
            alphavantage_api_key: Alpha Vantage API key.
            coingecko_api_key: CoinGecko API key (optional).
        """
        self.storage = MarketDataStorage(storage_path)
        self.sources: Dict[DataSource, BaseDataSource] = {}

        if yahoo_enabled:
            self.sources[DataSource.YAHOO] = YahooFinanceSource()

        if coingecko_enabled:
            self.sources[DataSource.COINGECKO] = CoinGeckoSource(
                api_key=coingecko_api_key
            )

        if alphavantage_enabled:
            self.sources[DataSource.ALPHA_VANTAGE] = AlphaVantageSource(
                api_key=alphavantage_api_key
            )

        if binance_enabled:
            from src.data.sources.binance import BinanceSource

            self.sources[DataSource.BINANCE] = BinanceSource()

        # Register data sources in storage
        for source_name, source in self.sources.items():
            self.storage.upsert_data_source(
                name=source_name.value,
                enabled=True,
                rate_limit=source.rate_limiter.max_requests,
            )

    def __enter__(self) -> "MarketDataCollector":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - closes connections."""
        self.close()

    def _register_symbol(self, symbol: str) -> None:
        """Register a symbol in the database if not already tracked."""
        if not self.storage.symbol_exists(symbol):
            asset_type = get_asset_type(symbol)
            preferred_sources = SYMBOL_SOURCE_MAP.get(
                symbol, [DataSource.YAHOO]
            )
            self.storage.upsert_symbol(
                Symbol(
                    symbol=symbol,
                    name=symbol,
                    asset_type=asset_type,
                    source=preferred_sources[0],
                )
            )

    def _get_sources_for_symbol(
        self, symbol: str, preferred_source: Optional[DataSource] = None
    ) -> List[DataSource]:
        """Get ordered list of sources to try for a symbol."""
        if preferred_source is not None:
            # Try preferred first, then fall back to defaults
            defaults = SYMBOL_SOURCE_MAP.get(symbol, [DataSource.YAHOO])
            sources = [preferred_source] + [s for s in defaults if s != preferred_source]
        else:
            sources = SYMBOL_SOURCE_MAP.get(symbol, [DataSource.YAHOO])

        # Filter to available sources
        return [s for s in sources if s in self.sources]

    def collect(
        self,
        symbol: str,
        source: Optional[DataSource] = None,
        period: str = "1y",
        interval: str = "1d",
    ) -> CollectionResult:
        """Collect data for a single symbol.

        Tries sources in order of preference, falling back on failure.

        Args:
            symbol: Ticker symbol to collect.
            source: Preferred data source (optional).
            period: Time period to fetch.
            interval: Data interval.

        Returns:
            CollectionResult with details of the operation.
        """
        start_time = time.time()
        self._register_symbol(symbol)

        sources_to_try = self._get_sources_for_symbol(symbol, source)

        if not sources_to_try:
            return CollectionResult(
                symbol=symbol,
                source=source or DataSource.YAHOO,
                success=False,
                error_message="No available data sources",
                duration_seconds=time.time() - start_time,
            )

        last_error: Optional[str] = None
        for source_name in sources_to_try:
            data_source = self.sources[source_name]
            try:
                logger.info(f"Collecting {symbol} from {source_name.value}")
                records = data_source.fetch_ohlcv(
                    symbol, period=period, interval=interval
                )

                if records:
                    count = self.storage.upsert_ohlcv_batch(records)
                    logger.info(f"Stored {count} records for {symbol}")
                    return CollectionResult(
                        symbol=symbol,
                        source=source_name,
                        records_collected=count,
                        success=True,
                        duration_seconds=time.time() - start_time,
                    )
                else:
                    last_error = f"No data returned from {source_name.value}"
                    logger.warning(f"No data for {symbol} from {source_name.value}")
                    continue

            except Exception as e:
                last_error = f"{source_name.value}: {str(e)}"
                logger.warning(
                    f"Failed to collect {symbol} from {source_name.value}: {e}"
                )
                continue

        return CollectionResult(
            symbol=symbol,
            source=sources_to_try[0] if sources_to_try else DataSource.YAHOO,
            success=False,
            error_message=last_error or "All sources failed",
            duration_seconds=time.time() - start_time,
        )

    def collect_batch(
        self,
        symbols: List[str],
        sources: Optional[List[DataSource]] = None,
        period: str = "1y",
        interval: str = "1d",
    ) -> CollectionBatchResult:
        """Collect data for multiple symbols.

        Args:
            symbols: List of ticker symbols.
            sources: Preferred data sources (optional).
            period: Time period to fetch.
            interval: Data interval.

        Returns:
            CollectionBatchResult with summary of all operations.
        """
        start_time = time.time()
        results: List[CollectionResult] = []

        for symbol in symbols:
            preferred = sources[0] if sources else None
            result = self.collect(
                symbol,
                source=preferred,
                period=period,
                interval=interval,
            )
            results.append(result)

            # Small delay between symbols to be polite to APIs
            time.sleep(0.1)

        total_records = sum(r.records_collected for r in results)
        successful = sum(1 for r in results if r.success)
        failed = len(results) - successful

        return CollectionBatchResult(
            results=results,
            total_records=total_records,
            successful_symbols=successful,
            failed_symbols=failed,
            duration_seconds=time.time() - start_time,
        )

    def get_latest(
        self, symbol: str, source: Optional[DataSource] = None
    ) -> Optional[MarketData]:
        """Get the most recent data point for a symbol.

        Args:
            symbol: Ticker symbol.
            source: Optional filter by data source.

        Returns:
            Most recent MarketData or None.
        """
        return self.storage.get_latest(symbol, source)

    def get_history(
        self,
        symbol: str,
        days: int = 365,
        source: Optional[DataSource] = None,
    ) -> pd.DataFrame:
        """Get historical data for a symbol.

        Args:
            symbol: Ticker symbol.
            days: Number of days of history.
            source: Optional filter by data source.

        Returns:
            DataFrame with historical data.
        """
        return self.storage.get_history(symbol, days, source)

    def list_symbols(self, active_only: bool = True) -> List[Symbol]:
        """List all tracked symbols.

        Args:
            active_only: Only return active symbols.

        Returns:
            List of Symbol records.
        """
        return self.storage.list_symbols(active_only)

    def get_collection_stats(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get collection statistics.

        Args:
            symbol: Optional symbol to get stats for.

        Returns:
            Dictionary with collection statistics.
        """
        stats: Dict[str, Any] = {}

        for source in DataSource:
            count = self.storage.get_record_count(symbol=symbol, source=source)
            stats[source.value] = count

        stats["total"] = self.storage.get_record_count(symbol=symbol)

        if symbol:
            date_range = self.storage.get_date_range(symbol)
            if date_range:
                stats["earliest"] = date_range[0].isoformat()
                stats["latest"] = date_range[1].isoformat()

        return stats

    def initialize_default_symbols(self) -> int:
        """Initialize the database with all default supported symbols.

        Returns:
            Number of symbols registered.
        """
        all_symbols = (
            DEFAULT_STOCKS + DEFAULT_CRYPTO + DEFAULT_FOREX + DEFAULT_COMMODITIES
        )

        count = 0
        for sym in all_symbols:
            if not self.storage.symbol_exists(sym):
                self._register_symbol(sym)
                count += 1

        logger.info(f"Initialized {count} new symbols")
        return count

    def close(self) -> None:
        """Close all connections and clean up."""
        self.storage.close()
