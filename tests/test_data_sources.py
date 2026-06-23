"""Data source tests for the unified trading system.

Run: pytest tests/test_data_sources.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.sources.binance import BinanceSource, BINANCE_SYMBOL_MAP


class TestBinanceSource:
    @pytest.fixture(autouse=True)
    def _skip_if_blocked(self):
        """Skip tests when Binance blocks the region (HTTP 451)."""
        src = BinanceSource()
        if not src.is_available():
            pytest.skip("Binance API blocked from this network (HTTP 451)")

    def test_is_available(self):
        src = BinanceSource()
        assert src.is_available() is True

    def test_fetch_price_btc(self):
        src = BinanceSource()
        price = src.fetch_price("BTC")
        assert price is not None
        assert price > 0
        assert price > 1000  # sanity check: BTC is always > $1k

    def test_fetch_price_sol(self):
        src = BinanceSource()
        price = src.fetch_price("SOL")
        assert price is not None
        assert price > 0

    def test_fetch_prices_bulk(self):
        src = BinanceSource()
        prices = src.fetch_prices(["BTC", "ETH", "SOL"])
        assert prices["BTC"] is not None and prices["BTC"] > 0
        assert prices["ETH"] is not None and prices["ETH"] > 0
        assert prices["SOL"] is not None and prices["SOL"] > 0

    def test_fetch_ohlcv_btc_daily(self):
        src = BinanceSource()
        candles = src.fetch_ohlcv("BTC", period="30d", interval="1d")
        assert len(candles) >= 25  # ~30 daily candles
        first = candles[0]
        assert first.symbol == "BTC"
        assert first.high >= first.low
        assert first.high >= max(first.open, first.close)
        assert first.low <= min(first.open, first.close)
        assert first.close > 0
        assert first.source.value == "binance"

    def test_fetch_ohlcv_eth_hourly(self):
        src = BinanceSource()
        candles = src.fetch_ohlcv("ETH", period="7d", interval="1h")
        # 7 days * 24h = 168 candles max
        assert 100 <= len(candles) <= 170

    def test_24h_ticker(self):
        src = BinanceSource()
        data = src.fetch_24h("BTC")
        assert data is not None
        assert "lastPrice" in data
        assert "priceChangePercent" in data

    def test_symbol_map_coverage(self):
        """All common crypto symbols are mapped to USDT pairs (no network)."""
        for sym in ("BTC", "ETH", "SOL", "DOGE", "BNB", "XRP"):
            assert sym in BINANCE_SYMBOL_MAP
            assert BINANCE_SYMBOL_MAP[sym].endswith("USDT")

    def test_unknown_symbol_fallback(self):
        """Unknown symbol gets pair suffix automatically (no network)."""
        from src.data.sources.binance import BinanceSource as _BS

        s = _BS()
        assert s._to_pair("ATOM") == "ATOMUSDT"
        assert s._to_pair("BTC") == "BTCUSDT"
