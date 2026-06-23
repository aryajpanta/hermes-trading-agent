"""Data models for the Market Data Collection System.

Uses Pydantic v2 for validation and serialization. All models are immutable
with frozen=True where applicable for data integrity.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class DataSource(str, Enum):
    """Supported data sources."""

    YAHOO = "yahoo"
    COINGECKO = "coingecko"
    ALPHA_VANTAGE = "alpha_vantage"
    BINANCE = "binance"


class Symbol(BaseModel):
    """Represents a tracked financial symbol."""

    symbol: str = Field(..., min_length=1, max_length=20, description="Ticker symbol")
    name: str = Field(default="", description="Full name of the asset")
    asset_type: str = Field(
        default="stock", description="Type: stock, crypto, forex, commodity"
    )
    source: DataSource = Field(
        default=DataSource.YAHOO, description="Primary data source"
    )
    is_active: bool = Field(default=True, description="Whether tracking is active")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {"frozen": True}


class MarketData(BaseModel):
    """OHLCV market data point with metadata."""

    symbol: str = Field(..., min_length=1, max_length=20)
    timestamp: datetime = Field(...)
    open: float = Field(..., ge=0)
    high: float = Field(..., ge=0)
    low: float = Field(..., ge=0)
    close: float = Field(..., ge=0)
    volume: int = Field(..., ge=0)
    source: DataSource
    metadata: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"frozen": True}

    def model_post_init(self, __context: Any) -> None:
        """Validate OHLCV consistency after initialization."""
        if self.high < self.low:
            raise ValueError(
                f"High ({self.high}) must be >= Low ({self.low})"
            )
        if self.high < max(self.open, self.close):
            raise ValueError(
                f"High ({self.high}) must be >= Open ({self.open}) and Close ({self.close})"
            )
        if self.low > min(self.open, self.close):
            raise ValueError(
                f"Low ({self.low}) must be <= Open ({self.open}) and Close ({self.close})"
            )


class CollectionResult(BaseModel):
    """Result of a data collection operation."""

    symbol: str
    source: DataSource
    records_collected: int = Field(default=0, ge=0)
    success: bool = Field(default=True)
    error_message: Optional[str] = Field(default=None)
    duration_seconds: float = Field(default=0.0, ge=0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CollectionBatchResult(BaseModel):
    """Result of a batch collection operation."""

    results: List[CollectionResult] = Field(default_factory=list)
    total_records: int = Field(default=0, ge=0)
    successful_symbols: int = Field(default=0, ge=0)
    failed_symbols: int = Field(default=0, ge=0)
    duration_seconds: float = Field(default=0.0, ge=0)


# Default symbol lists for supported assets
DEFAULT_STOCKS: List[str] = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "BRK-B", "JPM", "V",
    "JNJ", "WMT", "PG", "MA", "HD",
    "UNH", "XOM", "CVX", "ABBV", "MRK",
]

DEFAULT_CRYPTO: List[str] = ["BTC", "ETH", "SOL"]

DEFAULT_FOREX: List[str] = ["EUR-USD", "GBP-USD"]

DEFAULT_COMMODITIES: List[str] = ["GC=F", "SI=F"]

# Yahoo Finance symbol mappings for non-standard tickers
YAHOO_SYMBOL_MAP: Dict[str, str] = {
    "BRK-B": "BRK-B",
    "GC=F": "GC=F",
    "SI=F": "SI=F",
    "EUR-USD": "EURUSD=X",
    "GBP-USD": "GBPUSD=X",
}

# CoinGecko ID mappings
COINGECKO_MAP: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
}


def get_asset_type(symbol: str) -> str:
    """Determine asset type from symbol."""
    if symbol in DEFAULT_CRYPTO:
        return "crypto"
    if symbol in DEFAULT_FOREX or symbol.endswith("-USD"):
        return "forex"
    if symbol in DEFAULT_COMMODITIES or symbol in ("GC=F", "SI=F"):
        return "commodity"
    return "stock"
