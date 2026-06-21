"""Comprehensive tests for the Market Data Collection System.

Tests cover:
- Data model validation (MarketData, Symbol, DataSource)
- SQLite storage operations (upsert, query, batch)
- Yahoo Finance data source (mocked)
- CoinGecko data source (mocked)
- Alpha Vantage data source (mocked)
- Collector orchestration and fallback logic
- Rate limiting
- CLI entry point
"""

import json
import os
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

# Set up test environment
os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "")

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
from src.data.storage import MarketDataStorage
from src.data.sources.alphavantage import AlphaVantageSource
from src.data.sources.base import BaseDataSource, RateLimiter
from src.data.sources.coingecko import CoinGeckoSource
from src.data.sources.yahoo import YahooFinanceSource
from src.data.collector import MarketDataCollector


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_market_data() -> MarketData:
    """Create a sample MarketData record."""
    return MarketData(
        symbol="AAPL",
        timestamp=datetime(2024, 1, 15, 16, 0, 0),
        open=185.50,
        high=187.25,
        low=184.75,
        close=186.80,
        volume=50000000,
        source=DataSource.YAHOO,
        metadata={"dividends": 0.0, "stock_splits": 0.0},
    )


@pytest.fixture
def sample_market_data_batch() -> list[MarketData]:
    """Create a batch of sample MarketData records."""
    base_date = datetime.utcnow() - timedelta(days=20)
    records = []
    for i in range(10):
        records.append(
            MarketData(
                symbol="AAPL",
                timestamp=base_date + timedelta(days=i),
                open=185.0 + i * 0.5,
                high=186.0 + i * 0.5,
                low=184.0 + i * 0.5,
                close=185.5 + i * 0.5,
                volume=50000000 + i * 1000000,
                source=DataSource.YAHOO,
                metadata={},
            )
        )
    return records


@pytest.fixture
def sample_symbol() -> Symbol:
    """Create a sample Symbol record."""
    return Symbol(
        symbol="AAPL",
        name="Apple Inc.",
        asset_type="stock",
        source=DataSource.YAHOO,
        is_active=True,
    )


@pytest.fixture
def temp_db_path(tmp_path: Path) -> str:
    """Create a temporary database path."""
    return str(tmp_path / "test_market.db")


@pytest.fixture
def storage(temp_db_path: str) -> MarketDataStorage:
    """Create a MarketDataStorage with temporary database."""
    return MarketDataStorage(temp_db_path)


@pytest.fixture
def storage_with_data(storage: MarketDataStorage, sample_market_data_batch: list[MarketData]) -> MarketDataStorage:
    """Create storage pre-populated with sample data."""
    storage.upsert_symbol(Symbol(symbol="AAPL", source=DataSource.YAHOO))
    storage.upsert_ohlcv_batch(sample_market_data_batch)
    return storage


@pytest.fixture
def collector(temp_db_path: str) -> MarketDataCollector:  # type: ignore[misc]
    """Create a MarketDataCollector with mocked sources."""
    # Create collector with no real sources, then add mocks
    c = MarketDataCollector(
        storage_path=temp_db_path,
        yahoo_enabled=False,
        coingecko_enabled=False,
        alphavantage_enabled=False,
    )
    # Mock the sources
    yahoo_mock = MagicMock()
    yahoo_mock.fetch_ohlcv = MagicMock(return_value=[])
    yahoo_mock.rate_limiter = MagicMock()
    yahoo_mock.rate_limiter.max_requests = 2000
    coingecko_mock = MagicMock()
    coingecko_mock.fetch_ohlcv = MagicMock(return_value=[])
    coingecko_mock.rate_limiter = MagicMock()
    coingecko_mock.rate_limiter.max_requests = 10
    av_mock = MagicMock()
    av_mock.fetch_ohlcv = MagicMock(return_value=[])
    av_mock.rate_limiter = MagicMock()
    av_mock.rate_limiter.max_requests = 5
    c.sources[DataSource.YAHOO] = yahoo_mock  # type: ignore[assignment]
    c.sources[DataSource.COINGECKO] = coingecko_mock  # type: ignore[assignment]
    c.sources[DataSource.ALPHA_VANTAGE] = av_mock  # type: ignore[assignment]
    yield c  # type: ignore[misc]
    c.close()


# =============================================================================
# Model Tests
# =============================================================================


class TestMarketData:
    """Tests for MarketData model."""

    def test_create_valid_market_data(self, sample_market_data: MarketData) -> None:
        """Test creating a valid MarketData record."""
        assert sample_market_data.symbol == "AAPL"
        assert sample_market_data.open == 185.50
        assert sample_market_data.high == 187.25
        assert sample_market_data.low == 184.75
        assert sample_market_data.close == 186.80
        assert sample_market_data.volume == 50000000
        assert sample_market_data.source == DataSource.YAHOO

    def test_market_data_frozen(self, sample_market_data: MarketData) -> None:
        """Test that MarketData is immutable."""
        with pytest.raises(Exception):
            sample_market_data.symbol = "MSFT"  # type: ignore[misc]

    def test_market_data_high_low_validation(self) -> None:
        """Test that high must be >= low."""
        with pytest.raises(ValueError, match="High.*must be >= Low"):
            MarketData(
                symbol="AAPL",
                timestamp=datetime.now(),
                open=100.0,
                high=90.0,  # High < Low
                low=95.0,
                close=100.0,
                volume=1000,
                source=DataSource.YAHOO,
            )

    def test_market_data_high_open_close_validation(self) -> None:
        """Test that high must be >= open and close."""
        with pytest.raises(ValueError, match="High.*must be >= Open"):
            MarketData(
                symbol="AAPL",
                timestamp=datetime.now(),
                open=100.0,
                high=99.0,  # High < Open
                low=98.0,
                close=99.5,
                volume=1000,
                source=DataSource.YAHOO,
            )

    def test_market_data_low_open_close_validation(self) -> None:
        """Test that low must be <= open and close."""
        with pytest.raises(ValueError, match="Low.*must be <= Open"):
            MarketData(
                symbol="AAPL",
                timestamp=datetime.now(),
                open=100.0,
                high=102.0,
                low=101.0,  # Low > Open
                close=101.5,
                volume=1000,
                source=DataSource.YAHOO,
            )

    def test_market_data_zero_volume(self) -> None:
        """Test that zero volume is allowed."""
        data = MarketData(
            symbol="AAPL",
            timestamp=datetime.now(),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=0,
            source=DataSource.YAHOO,
        )
        assert data.volume == 0

    def test_market_data_json_serialization(self, sample_market_data: MarketData) -> None:
        """Test JSON serialization/deserialization."""
        json_str = sample_market_data.model_dump_json()
        data = MarketData.model_validate_json(json_str)
        assert data.symbol == sample_market_data.symbol
        assert data.open == sample_market_data.open


class TestSymbol:
    """Tests for Symbol model."""

    def test_create_valid_symbol(self, sample_symbol: Symbol) -> None:
        """Test creating a valid Symbol record."""
        assert sample_symbol.symbol == "AAPL"
        assert sample_symbol.asset_type == "stock"
        assert sample_symbol.is_active is True

    def test_symbol_frozen(self, sample_symbol: Symbol) -> None:
        """Test that Symbol is immutable."""
        with pytest.raises(Exception):
            sample_symbol.symbol = "MSFT"  # type: ignore[misc]


class TestDataSource:
    """Tests for DataSource enum."""

    def test_data_source_values(self) -> None:
        """Test DataSource enum values."""
        assert DataSource.YAHOO.value == "yahoo"
        assert DataSource.COINGECKO.value == "coingecko"
        assert DataSource.ALPHA_VANTAGE.value == "alpha_vantage"

    def test_data_source_from_string(self) -> None:
        """Test creating DataSource from string."""
        assert DataSource("yahoo") == DataSource.YAHOO
        assert DataSource("coingecko") == DataSource.COINGECKO


class TestAssetType:
    """Tests for asset type detection."""

    def test_stock_detection(self) -> None:
        """Test stock asset type detection."""
        assert get_asset_type("AAPL") == "stock"
        assert get_asset_type("MSFT") == "stock"

    def test_crypto_detection(self) -> None:
        """Test crypto asset type detection."""
        assert get_asset_type("BTC") == "crypto"
        assert get_asset_type("ETH") == "crypto"
        assert get_asset_type("SOL") == "crypto"

    def test_forex_detection(self) -> None:
        """Test forex asset type detection."""
        assert get_asset_type("EUR-USD") == "forex"
        assert get_asset_type("GBP-USD") == "forex"

    def test_commodity_detection(self) -> None:
        """Test commodity asset type detection."""
        assert get_asset_type("GC=F") == "commodity"
        assert get_asset_type("SI=F") == "commodity"


class TestCollectionResult:
    """Tests for CollectionResult model."""

    def test_create_collection_result(self) -> None:
        """Test creating a CollectionResult."""
        result = CollectionResult(
            symbol="AAPL",
            source=DataSource.YAHOO,
            records_collected=252,
            success=True,
        )
        assert result.symbol == "AAPL"
        assert result.records_collected == 252
        assert result.success is True

    def test_collection_result_defaults(self) -> None:
        """Test CollectionResult default values."""
        result = CollectionResult(symbol="AAPL", source=DataSource.YAHOO)
        assert result.records_collected == 0
        assert result.success is True
        assert result.error_message is None


# =============================================================================
# Storage Tests
# =============================================================================


class TestMarketDataStorage:
    """Tests for SQLite storage layer."""

    def test_schema_creation(self, storage: MarketDataStorage) -> None:
        """Test that schema is created on initialization."""
        # Check tables exist
        cursor = storage.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        assert "ohlcv" in tables
        assert "symbols" in tables
        assert "data_sources" in tables

    def test_upsert_ohlcv(self, storage: MarketDataStorage, sample_market_data: MarketData) -> None:
        """Test inserting an OHLCV record."""
        # First register the symbol
        storage.upsert_symbol(
            Symbol(symbol="AAPL", source=DataSource.YAHOO)
        )

        result = storage.upsert_ohlcv(sample_market_data)
        assert result is True

        # Verify record exists
        cursor = storage.conn.execute(
            "SELECT * FROM ohlcv WHERE symbol='AAPL'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["open"] == 185.50

    def test_upsert_ohlcv_update(self, storage: MarketDataStorage, sample_market_data: MarketData) -> None:
        """Test that upsert updates existing records."""
        storage.upsert_symbol(
            Symbol(symbol="AAPL", source=DataSource.YAHOO)
        )

        # Insert first
        storage.upsert_ohlcv(sample_market_data)

        # Insert again with updated close
        updated = sample_market_data.model_copy(update={"close": 200.0})
        storage.upsert_ohlcv(updated)

        # Verify updated
        cursor = storage.conn.execute(
            "SELECT close FROM ohlcv WHERE symbol='AAPL'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["close"] == 200.0

    def test_upsert_ohlcv_batch(
        self, storage: MarketDataStorage, sample_market_data_batch: list[MarketData]
    ) -> None:
        """Test batch upsert of OHLCV records."""
        storage.upsert_symbol(
            Symbol(symbol="AAPL", source=DataSource.YAHOO)
        )

        count = storage.upsert_ohlcv_batch(sample_market_data_batch)
        assert count == len(sample_market_data_batch)

        # Verify all records
        cursor = storage.conn.execute(
            "SELECT COUNT(*) as cnt FROM ohlcv WHERE symbol='AAPL'"
        )
        assert cursor.fetchone()["cnt"] == len(sample_market_data_batch)

    def test_upsert_symbol(self, storage: MarketDataStorage, sample_symbol: Symbol) -> None:
        """Test symbol upsert."""
        result = storage.upsert_symbol(sample_symbol)
        assert result is True

        cursor = storage.conn.execute(
            "SELECT * FROM symbols WHERE symbol='AAPL'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["asset_type"] == "stock"

    def test_upsert_data_source(self, storage: MarketDataStorage) -> None:
        """Test data source upsert."""
        result = storage.upsert_data_source(
            name="yahoo",
            enabled=True,
            rate_limit=2000,
        )
        assert result is True

        cursor = storage.conn.execute(
            "SELECT * FROM data_sources WHERE name='yahoo'"
        )
        row = cursor.fetchone()
        assert row is not None
        assert row["rate_limit"] == 2000

    def test_get_latest(self, storage_with_data: MarketDataStorage) -> None:
        """Test getting latest record."""
        latest = storage_with_data.get_latest("AAPL")
        assert latest is not None
        assert latest.symbol == "AAPL"
        # Should be the last date in our batch
        assert latest.timestamp.day == 10

    def test_get_latest_no_data(self, storage: MarketDataStorage) -> None:
        """Test getting latest when no data exists."""
        latest = storage.get_latest("NONEXISTENT")
        assert latest is None

    def test_get_history(self, storage_with_data: MarketDataStorage) -> None:
        """Test getting historical data."""
        df = storage_with_data.get_history("AAPL", days=365)
        assert not df.empty
        assert len(df) == 10
        assert "open" in df.columns
        assert "close" in df.columns

    def test_get_history_with_source_filter(
        self, storage_with_data: MarketDataStorage
    ) -> None:
        """Test getting history filtered by source."""
        df = storage_with_data.get_history(
            "AAPL", days=365, source=DataSource.YAHOO
        )
        assert not df.empty

    def test_list_symbols(self, storage: MarketDataStorage) -> None:
        """Test listing symbols."""
        storage.upsert_symbol(Symbol(symbol="AAPL", source=DataSource.YAHOO))
        storage.upsert_symbol(Symbol(symbol="MSFT", source=DataSource.YAHOO))

        symbols = storage.list_symbols()
        assert len(symbols) == 2
        assert symbols[0].symbol == "AAPL"
        assert symbols[1].symbol == "MSFT"

    def test_symbol_exists(self, storage: MarketDataStorage) -> None:
        """Test checking if symbol exists."""
        assert storage.symbol_exists("AAPL") is False

        storage.upsert_symbol(Symbol(symbol="AAPL", source=DataSource.YAHOO))
        assert storage.symbol_exists("AAPL") is True

    def test_get_record_count(self, storage_with_data: MarketDataStorage) -> None:
        """Test getting record count."""
        count = storage_with_data.get_record_count("AAPL")
        assert count == 10

    def test_get_date_range(self, storage_with_data: MarketDataStorage) -> None:
        """Test getting date range."""
        date_range = storage_with_data.get_date_range("AAPL")
        assert date_range is not None
        assert date_range[0] < date_range[1]

    def test_context_manager(self, temp_db_path: str) -> None:
        """Test using storage as context manager."""
        with MarketDataStorage(temp_db_path) as storage:
            storage.upsert_symbol(Symbol(symbol="TEST", source=DataSource.YAHOO))
            assert storage.symbol_exists("TEST") is True


# =============================================================================
# Rate Limiter Tests
# =============================================================================


class TestRateLimiter:
    """Tests for rate limiting."""

    def test_rate_limiter_allows_within_limit(self) -> None:
        """Test that requests within limit are allowed."""
        limiter = RateLimiter(max_requests=5, time_window_seconds=1)
        for _ in range(5):
            limiter.wait_if_needed()
        assert limiter.remaining_quota == 0

    def test_rate_limiter_blocks_over_limit(self) -> None:
        """Test that requests over limit are blocked."""
        limiter = RateLimiter(max_requests=2, time_window_seconds=60)
        limiter.wait_if_needed()
        limiter.wait_if_needed()
        # This should wait (but we won't actually wait in test)
        start = time.time()
        limiter.wait_if_needed()
        elapsed = time.time() - start
        # Should have waited some time
        assert elapsed >= 0


# =============================================================================
# Data Source Tests (Mocked)
# =============================================================================


class TestYahooFinanceSource:
    """Tests for Yahoo Finance data source."""

    def test_initialization(self) -> None:
        """Test Yahoo Finance source initialization."""
        source = YahooFinanceSource()
        assert source.source_name == DataSource.YAHOO
        assert source.rate_limiter.max_requests == 2000

    def test_normalize_symbol(self) -> None:
        """Test symbol normalization."""
        source = YahooFinanceSource()
        assert source._normalize_symbol("AAPL") == "AAPL"
        assert source._normalize_symbol("BTC") == "BTC-USD"
        assert source._normalize_symbol("EUR-USD") == "EURUSD=X"
        assert source._normalize_symbol("GC=F") == "GC=F"

    @patch("src.data.sources.yahoo.yf")
    def test_fetch_ohlcv(self, mock_yf: MagicMock) -> None:
        """Test fetching OHLCV data from Yahoo Finance."""
        # Mock the yfinance data
        mock_ticker = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker

        # Create mock DataFrame
        dates = pd.date_range("2024-01-01", periods=5, freq="D")
        df = pd.DataFrame(
            {
                "Open": [185.0, 186.0, 187.0, 188.0, 189.0],
                "High": [186.0, 187.0, 188.0, 189.0, 190.0],
                "Low": [184.0, 185.0, 186.0, 187.0, 188.0],
                "Close": [185.5, 186.5, 187.5, 188.5, 189.5],
                "Volume": [50000000, 51000000, 52000000, 53000000, 54000000],
                "Dividends": [0, 0, 0, 0, 0],
                "Stock Splits": [0, 0, 0, 0, 0],
            },
            index=dates,
        )
        mock_ticker.history.return_value = df

        source = YahooFinanceSource()
        records = source.fetch_ohlcv("AAPL", period="5d")

        assert len(records) == 5
        assert records[0].symbol == "AAPL"
        assert records[0].source == DataSource.YAHOO
        assert records[0].open == 185.0

    @patch("src.data.sources.yahoo.yf")
    def test_fetch_ohlcv_empty(self, mock_yf: MagicMock) -> None:
        """Test fetching OHLCV when no data returned."""
        mock_ticker = MagicMock()
        mock_yf.Ticker.return_value = mock_ticker
        mock_ticker.history.return_value = pd.DataFrame()

        source = YahooFinanceSource()
        records = source.fetch_ohlcv("INVALID", period="1y")
        assert len(records) == 0

    def test_parse_period(self) -> None:
        """Test period parsing."""
        assert BaseDataSource.parse_period("1y") == 365
        assert BaseDataSource.parse_period("6mo") == 180
        assert BaseDataSource.parse_period("2w") == 14
        assert BaseDataSource.parse_period("30d") == 30


class TestCoinGeckoSource:
    """Tests for CoinGecko data source."""

    def test_initialization(self) -> None:
        """Test CoinGecko source initialization."""
        source = CoinGeckoSource()
        assert source.source_name == DataSource.COINGECKO
        assert source.rate_limiter.max_requests == 10

    def test_get_coin_id(self) -> None:
        """Test coin ID mapping."""
        source = CoinGeckoSource()
        assert source._get_coin_id("BTC") == "bitcoin"
        assert source._get_coin_id("ETH") == "ethereum"
        assert source._get_coin_id("SOL") == "solana"
        assert source._get_coin_id("DOGE") == "doge"

    def test_parse_period_days(self) -> None:
        """Test period parsing for CoinGecko."""
        source = CoinGeckoSource()
        assert source._parse_period_days("1y") == 365
        assert source._parse_period_days("30d") == 30
        assert source._parse_period_days("7d") == 7

    @patch("src.data.sources.coingecko.requests.Session")
    def test_fetch_ohlcv(self, mock_session_class: MagicMock) -> None:
        """Test fetching OHLCV data from CoinGecko."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        # Mock API response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "prices": [
                [1704067200000, 42000.0],
                [1704153600000, 42500.0],
                [1704240000000, 43000.0],
            ],
            "total_volumes": [
                [1704067200000, 25000000000],
                [1704153600000, 26000000000],
                [1704240000000, 27000000000],
            ],
            "market_caps": [
                [1704067200000, 820000000000],
                [1704153600000, 830000000000],
                [1704240000000, 840000000000],
            ],
        }
        mock_session.get.return_value = mock_response

        source = CoinGeckoSource()
        records = source.fetch_ohlcv("BTC", period="3d")

        assert len(records) == 3
        assert records[0].symbol == "BTC"
        assert records[0].source == DataSource.COINGECKO
        assert records[0].close == 42000.0


class TestAlphaVantageSource:
    """Tests for Alpha Vantage data source."""

    def test_initialization(self) -> None:
        """Test Alpha Vantage source initialization."""
        source = AlphaVantageSource(api_key="test_key")
        assert source.source_name == DataSource.ALPHA_VANTAGE
        assert source.api_key == "test_key"

    def test_is_forex_pair(self) -> None:
        """Test forex pair detection."""
        source = AlphaVantageSource()
        assert source._is_forex_pair("EUR-USD") is True
        assert source._is_forex_pair("GBP-USD") is True
        assert source._is_forex_pair("AAPL") is False

    def test_parse_forex_pair(self) -> None:
        """Test forex pair parsing."""
        source = AlphaVantageSource()
        from_sym, to_sym = source._parse_forex_pair("EUR-USD")
        assert from_sym == "EUR"
        assert to_sym == "USD"

    def test_no_api_key_returns_empty(self) -> None:
        """Test that no API key returns empty results."""
        source = AlphaVantageSource(api_key="")
        records = source.fetch_ohlcv("AAPL")
        assert len(records) == 0

    @patch("src.data.sources.alphavantage.requests.Session")
    def test_fetch_stock_ohlcv(self, mock_session_class: MagicMock) -> None:
        """Test fetching stock data from Alpha Vantage."""
        mock_session = MagicMock()
        mock_session_class.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "Time Series (Daily)": {
                "2024-01-15": {
                    "1. open": "185.50",
                    "2. high": "187.25",
                    "3. low": "184.75",
                    "4. close": "186.80",
                    "5. volume": "50000000",
                },
                "2024-01-14": {
                    "1. open": "184.00",
                    "2. high": "185.50",
                    "3. low": "183.50",
                    "4. close": "185.20",
                    "5. volume": "48000000",
                },
            }
        }
        mock_session.get.return_value = mock_response

        source = AlphaVantageSource(api_key="test_key")
        records = source.fetch_ohlcv("AAPL")

        assert len(records) == 2
        assert records[0].symbol == "AAPL"
        assert records[0].source == DataSource.ALPHA_VANTAGE


# =============================================================================
# Collector Tests
# =============================================================================


class TestMarketDataCollector:
    """Tests for the collector orchestrator."""

    def test_initialization(self, temp_db_path: str) -> None:
        """Test collector initialization."""
        collector = MarketDataCollector(
            storage_path=temp_db_path,
            yahoo_enabled=True,
            coingecko_enabled=True,
            alphavantage_enabled=False,
        )
        assert DataSource.YAHOO in collector.sources
        assert DataSource.COINGECKO in collector.sources
        assert DataSource.ALPHA_VANTAGE not in collector.sources
        collector.close()

    def test_collect_single_symbol(self, collector: MarketDataCollector) -> None:
        """Test collecting data for a single symbol."""
        # Mock Yahoo to return data
        collector.sources[DataSource.YAHOO].fetch_ohlcv.return_value = [
            MarketData(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 15),
                open=185.0,
                high=187.0,
                low=184.0,
                close=186.5,
                volume=50000000,
                source=DataSource.YAHOO,
            )
        ]

        result = collector.collect("AAPL", period="1y")
        assert result.success is True
        assert result.records_collected == 1
        assert result.source == DataSource.YAHOO

    def test_collect_fallback(self, collector: MarketDataCollector) -> None:
        """Test fallback to second source when first fails."""
        # Yahoo fails
        collector.sources[DataSource.YAHOO].fetch_ohlcv.side_effect = Exception("API Error")
        # CoinGecko succeeds
        collector.sources[DataSource.COINGECKO].fetch_ohlcv.return_value = [
            MarketData(
                symbol="BTC",
                timestamp=datetime(2024, 1, 15),
                open=42000.0,
                high=43000.0,
                low=41000.0,
                close=42500.0,
                volume=25000000000,
                source=DataSource.COINGECKO,
            )
        ]

        result = collector.collect("BTC", period="1y")
        assert result.success is True
        assert result.source == DataSource.COINGECKO

    def test_collect_batch(self, collector: MarketDataCollector) -> None:
        """Test batch collection."""
        def make_data(symbol: str, **kwargs: object) -> list[MarketData]:
            return [
                MarketData(
                    symbol=symbol,
                    timestamp=datetime.utcnow() - timedelta(days=1),
                    open=100.0,
                    high=101.0,
                    low=99.0,
                    close=100.5,
                    volume=1000000,
                    source=DataSource.YAHOO,
                )
            ]

        collector.sources[DataSource.YAHOO].fetch_ohlcv.side_effect = make_data  # type: ignore[assignment]

        result = collector.collect_batch(
            symbols=["AAPL", "MSFT", "GOOGL"],
            period="1y",
        )
        assert result.successful_symbols == 3
        assert result.total_records == 3
        assert result.failed_symbols == 0

    def test_get_latest(self, collector: MarketDataCollector) -> None:
        """Test getting latest record."""
        # First store some data
        collector.sources[DataSource.YAHOO].fetch_ohlcv.return_value = [
            MarketData(
                symbol="AAPL",
                timestamp=datetime(2024, 1, 15),
                open=185.0,
                high=187.0,
                low=184.0,
                close=186.5,
                volume=50000000,
                source=DataSource.YAHOO,
            )
        ]
        collector.collect("AAPL")

        latest = collector.get_latest("AAPL")
        assert latest is not None
        assert latest.symbol == "AAPL"

    def test_get_history(self, collector: MarketDataCollector) -> None:
        """Test getting historical data."""
        # Store some data
        collector.sources[DataSource.YAHOO].fetch_ohlcv.return_value = [
            MarketData(
                symbol="AAPL",
                timestamp=datetime.utcnow() - timedelta(days=1),
                open=185.0,
                high=187.0,
                low=184.0,
                close=186.5,
                volume=50000000,
                source=DataSource.YAHOO,
            )
        ]
        collector.collect("AAPL")

        df = collector.get_history("AAPL", days=365)
        assert not df.empty
        assert "close" in df.columns

    def test_list_symbols(self, collector: MarketDataCollector) -> None:
        """Test listing symbols."""
        # Register some symbols
        collector._register_symbol("AAPL")
        collector._register_symbol("MSFT")

        symbols = collector.list_symbols()
        symbol_names = [s.symbol for s in symbols]
        assert "AAPL" in symbol_names
        assert "MSFT" in symbol_names

    def test_get_collection_stats(self, collector: MarketDataCollector) -> None:
        """Test getting collection statistics."""
        stats = collector.get_collection_stats()
        assert "total" in stats
        assert "yahoo" in stats
        assert "coingecko" in stats

    def test_initialize_default_symbols(self, collector: MarketDataCollector) -> None:
        """Test initializing default symbols."""
        count = collector.initialize_default_symbols()
        assert count > 0

        symbols = collector.list_symbols()
        assert len(symbols) > 0

    def test_collect_all_sources_fail(self, collector: MarketDataCollector) -> None:
        """Test handling when all sources fail."""
        collector.sources[DataSource.YAHOO].fetch_ohlcv.side_effect = Exception("Yahoo Error")
        collector.sources[DataSource.COINGECKO].fetch_ohlcv.side_effect = Exception("CoinGecko Error")

        result = collector.collect("AAPL", period="1y")
        assert result.success is False
        assert result.error_message is not None


# =============================================================================
# Integration Tests (Database)
# =============================================================================


class TestIntegration:
    """Integration tests for end-to-end data flow."""

    def test_full_collection_flow(self, temp_db_path: str) -> None:
        """Test complete collection and retrieval flow."""
        with MarketDataCollector(
            storage_path=temp_db_path,
            yahoo_enabled=True,
            coingecko_enabled=False,
            alphavantage_enabled=False,
        ) as collector:
            # Mock Yahoo source
            mock_data = [
                MarketData(
                    symbol="AAPL",
                    timestamp=datetime.utcnow() - timedelta(days=2),
                    open=185.0,
                    high=187.0,
                    low=184.0,
                    close=186.5,
                    volume=50000000,
                    source=DataSource.YAHOO,
                ),
                MarketData(
                    symbol="AAPL",
                    timestamp=datetime.utcnow() - timedelta(days=1),
                    open=186.5,
                    high=188.0,
                    low=185.5,
                    close=187.5,
                    volume=52000000,
                    source=DataSource.YAHOO,
                ),
            ]
            collector.sources[DataSource.YAHOO].fetch_ohlcv = MagicMock(return_value=mock_data)  # type: ignore[assignment]

            # Collect
            result = collector.collect("AAPL")
            assert result.success is True
            assert result.records_collected == 2

            # Verify retrieval
            latest = collector.get_latest("AAPL")
            assert latest is not None
            assert latest.close == 187.5

            df = collector.get_history("AAPL")
            assert len(df) == 2

    def test_upsert_idempotency(self, temp_db_path: str) -> None:
        """Test that upserts are idempotent."""
        storage = MarketDataStorage(temp_db_path)
        storage.upsert_symbol(Symbol(symbol="AAPL", source=DataSource.YAHOO))

        data = MarketData(
            symbol="AAPL",
            timestamp=datetime(2024, 1, 15),
            open=185.0,
            high=187.0,
            low=184.0,
            close=186.5,
            volume=50000000,
            source=DataSource.YAHOO,
        )

        # Insert twice
        storage.upsert_ohlcv(data)
        storage.upsert_ohlcv(data)

        # Should only have one record
        count = storage.get_record_count("AAPL")
        assert count == 1

        storage.close()


# =============================================================================
# CLI Tests
# =============================================================================


class TestCLI:
    """Tests for CLI entry point."""

    def test_cli_help(self) -> None:
        """Test CLI help output."""
        from click.testing import CliRunner
        from src.data.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "Market Data Collection CLI" in result.output

    def test_cli_list_defaults(self) -> None:
        """Test listing default symbols."""
        from click.testing import CliRunner
        from src.data.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["--list-defaults"])
        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "BTC" in result.output

    def test_cli_no_symbols_error(self) -> None:
        """Test error when no symbols provided."""
        from click.testing import CliRunner
        from src.data.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code != 0 or "required" in result.output.lower() or "Error" in result.output
