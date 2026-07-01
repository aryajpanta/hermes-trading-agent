"""Tests for the volume data source."""
import pandas as pd
from src.data.sources.volume import VolumeSource


def test_equity_volume_returns_dataframe_with_volume_column():
    src = VolumeSource()
    df = src.get_volume("AAPL", period="5d", interval="1h")
    assert isinstance(df, pd.DataFrame)
    assert "volume" in df.columns


def test_crypto_volume_returns_dataframe_with_volume_column():
    src = VolumeSource()
    df = src.get_volume("BTC-USD", period="5d", interval="1h")
    assert isinstance(df, pd.DataFrame)
    assert "volume" in df.columns


def test_invalid_ticker_returns_empty_dataframe():
    src = VolumeSource()
    df = src.get_volume("NONSENSE_TICKER_XYZ", period="5d", interval="1h")
    assert isinstance(df, pd.DataFrame)
    assert "volume" in df.columns
    # Should not raise
