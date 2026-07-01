"""Tests for LabelingBuilder."""
import json
import os
import tempfile

from src.learning.labeling.builder import LabelingBuilder
from src.learning.features.schema import LABEL_COLUMN, FEATURE_COLUMNS


def test_record_entry_then_close_produces_labeled_row():
    with tempfile.TemporaryDirectory() as d:
        b = LabelingBuilder(data_dir=d)
        b.record_entry("AAPL", "rsi_mean_reversion", qty=10, entry_price=200.0)
        rows = b.close_pending(exit_prices={"AAPL": 210.0})
        assert len(rows) == 1
        row = rows[0]
        assert LABEL_COLUMN in row
        # 210/200 - 1 = 0.05 (5%)
        assert abs(row[LABEL_COLUMN] - 0.05) < 1e-6
        for c in FEATURE_COLUMNS:
            assert c in row


def test_persists_to_jsonl():
    with tempfile.TemporaryDirectory() as d:
        b = LabelingBuilder(data_dir=d)
        b.record_entry("BTC-USD", "ma_crossover", qty=1, entry_price=50000.0)
        b.close_pending(exit_prices={"BTC-USD": 55000.0})
        # JSONL should exist
        assert os.path.exists(os.path.join(d, "labels.jsonl"))
        with open(os.path.join(d, "labels.jsonl")) as f:
            line = f.readline()
        rec = json.loads(line)
        assert rec[LABEL_COLUMN] == 0.10  # 55000/50000 - 1


def test_load_all_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        b = LabelingBuilder(data_dir=d)
        b.record_entry("AAPL", "rsi", qty=1, entry_price=100.0)
        b.close_pending(exit_prices={"AAPL": 110.0})
        df = b.load_all()
        assert len(df) == 1
        assert LABEL_COLUMN in df.columns


def test_partial_close_keeps_unclosed_open():
    with tempfile.TemporaryDirectory() as d:
        b = LabelingBuilder(data_dir=d)
        b.record_entry("AAPL", "rsi", qty=1, entry_price=100.0)
        b.record_entry("MSFT", "rsi", qty=1, entry_price=300.0)
        # Only close AAPL
        rows = b.close_pending(exit_prices={"AAPL": 110.0})
        assert len(rows) == 1
        assert rows[0]["symbol"] == "AAPL"
        # MSFT still open
        assert any(r["_close_symbol"] == "MSFT" for r in b._open)
