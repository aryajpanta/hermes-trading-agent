"""Data source tests for the unified trading system.

Run: pytest tests/test_data_sources.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.sources.binance import (
    BINANCE_SYMBOL_MAP,
    INTERVAL_MS,
    BinanceSource,
)


# ────────────────────────────────────────────────────────────────
# Offline tests — run anywhere, no network required
# ────────────────────────────────────────────────────────────────


class TestBinanceOffline:
    def test_symbol_map_coverage(self):
        for sym in ("BTC", "ETH", "SOL", "DOGE", "BNB", "XRP"):
            assert sym in BINANCE_SYMBOL_MAP
            assert BINANCE_SYMBOL_MAP[sym].endswith("USDT")

    def test_interval_map(self):
        assert INTERVAL_MS["1d"] == 86_400_000
        assert INTERVAL_MS["1h"] == 3_600_000
        assert INTERVAL_MS["1m"] == 60_000

    def test_to_pair_known(self):
        s = BinanceSource.__new__(BinanceSource)
        assert BinanceSource._to_pair(s, "BTC") == "BTCUSDT"
        assert BinanceSource._to_pair(s, "ETH") == "ETHUSDT"

    def test_to_pair_unknown_fallback(self):
        s = BinanceSource.__new__(BinanceSource)
        assert BinanceSource._to_pair(s, "ATOM") == "ATOMUSDT"

    def test_parse_interval_valid(self):
        s = BinanceSource.__new__(BinanceSource)
        assert BinanceSource._parse_interval(s, "1d") == "1d"
        assert BinanceSource._parse_interval(s, "1h") == "1h"
        assert BinanceSource._parse_interval(s, "invalid") == "1d"  # default


# ────────────────────────────────────────────────────────────────
# Online tests — skipped when Binance is blocked (HTTP 451 in US)
# ────────────────────────────────────────────────────────────────


class TestBinanceOnline:
    @pytest.fixture(autouse=True)
    def _skip_if_blocked(self):
        src = BinanceSource()
        if not src.is_available():
            pytest.skip("Binance API blocked from this network (HTTP 451)")

    def test_is_available(self):
        assert BinanceSource().is_available() is True

    def test_fetch_price_btc(self):
        price = BinanceSource().fetch_price("BTC")
        assert price is not None and price > 0 and price > 1000

    def test_fetch_price_sol(self):
        price = BinanceSource().fetch_price("SOL")
        assert price is not None and price > 0

    def test_fetch_prices_bulk(self):
        prices = BinanceSource().fetch_prices(["BTC", "ETH", "SOL"])
        assert prices["BTC"] and prices["BTC"] > 0
        assert prices["ETH"] and prices["ETH"] > 0
        assert prices["SOL"] and prices["SOL"] > 0

    def test_fetch_ohlcv_btc_daily(self):
        candles = BinanceSource().fetch_ohlcv("BTC", period="30d", interval="1d")
        assert len(candles) >= 25
        first = candles[0]
        assert first.symbol == "BTC"
        assert first.high >= first.low
        assert first.close > 0
        assert first.source.value == "binance"

    def test_fetch_24h_ticker(self):
        data = BinanceSource().fetch_24h("BTC")
        assert data is not None
        assert "lastPrice" in data
