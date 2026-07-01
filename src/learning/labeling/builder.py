"""Outcome labeling — entry snapshot + close PnL = one training row.

Flow:
  1. record_entry(symbol, strategy_id, qty, entry_price)
     - Captures the live feature vector for (symbol, strategy_id)
     - Stores an open-entry record in memory
  2. close_pending(exit_prices: {symbol: exit_price})
     - For each open entry: compute realized_pnl_pct = exit/entry - 1
     - Merge with the entry snapshot
     - Persist to data/learning/labels.parquet (append)
     - Return the labeled rows (in-memory)
"""
from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.learning.features.schema import ALL_COLUMNS, LABEL_COLUMN
from src.learning.features.store import FeatureStore

logger = logging.getLogger(__name__)


class LabelingBuilder:
    def __init__(self, data_dir: str = "data/learning") -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.parquet_path = self.data_dir / "labels.parquet"
        self.jsonl_path = self.data_dir / "labels.jsonl"
        self._store = FeatureStore()
        self._open: List[Dict[str, Any]] = []

    def record_entry(
        self, symbol: str, strategy_id: str, qty: float, entry_price: float,
        ts: Optional[datetime] = None,
    ) -> None:
        ts = ts or datetime.now(timezone.utc)
        features = self._store.materialize(symbol, strategy_id, ts)
        features["entry_price"] = entry_price
        features["entry_qty"] = qty
        features["entry_ts"] = ts.isoformat()
        features["_close_symbol"] = symbol
        self._open.append(features)

    def close_pending(
        self, exit_prices: Dict[str, float], ts: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Mark all open entries for given symbols as closed. Returns labeled rows."""
        ts = ts or datetime.now(timezone.utc)
        labeled: List[Dict[str, Any]] = []
        still_open: List[Dict[str, Any]] = []
        for row in self._open:
            sym = row["_close_symbol"]
            if sym not in exit_prices:
                still_open.append(row)
                continue
            entry_px = float(row.get("entry_price", 0))
            exit_px = float(exit_prices[sym])
            if entry_px <= 0:
                continue
            row[LABEL_COLUMN] = (exit_px - entry_px) / entry_px
            row["exit_price"] = exit_px
            row["exit_ts"] = ts.isoformat()
            row["hold_hours"] = (
                ts - datetime.fromisoformat(row["entry_ts"])
            ).total_seconds() / 3600.0
            labeled.append(row)
        self._open = still_open
        if labeled:
            self._persist(labeled)
        return labeled

    def _persist(self, rows: List[Dict[str, Any]]) -> None:
        # JSONL always (append-only, robust)
        with open(self.jsonl_path, "a") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        # Parquet if pyarrow available
        try:
            existing = (
                pd.read_parquet(self.parquet_path) if self.parquet_path.exists()
                else pd.DataFrame()
            )
            combined = pd.concat([existing, pd.DataFrame(rows)], ignore_index=True)
            combined.to_parquet(self.parquet_path, index=False)
        except Exception as e:
            logger.debug("parquet persist failed (jsonl is canonical): %s", e)

    def load_all(self) -> pd.DataFrame:
        """Load all labeled rows. Reads both parquet (preferred) and jsonl,
        deduping by entry_ts+symbol+strategy_id+exit_ts."""
        from src.learning.features.schema import ALL_COLUMNS
        dfs = []
        if self.parquet_path.exists():
            try:
                dfs.append(pd.read_parquet(self.parquet_path))
            except Exception:
                pass
        if self.jsonl_path.exists():
            try:
                dfs.append(pd.read_json(self.jsonl_path, lines=True))
            except Exception:
                pass
        if not dfs:
            return pd.DataFrame()
        combined = pd.concat(dfs, ignore_index=True, sort=False)
        # Dedupe on the natural key
        dedupe_keys = ["entry_ts", "symbol", "strategy_id", "exit_ts"]
        if all(k in combined.columns for k in dedupe_keys):
            combined = combined.drop_duplicates(subset=dedupe_keys, keep="last")
        return combined
