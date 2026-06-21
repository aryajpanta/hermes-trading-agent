"""SQLite storage layer for market data with upsert support.

Provides a thread-safe storage backend that handles schema creation,
data persistence, and querying of OHLCV market data.
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.data.models import DataSource, MarketData, Symbol


class MarketDataStorage:
    """SQLite-backed storage for market data with upsert capabilities."""

    def __init__(self, db_path: str = "data/market.db") -> None:
        """Initialize storage and create schema if needed.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._create_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        """Get or create a database connection."""
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _create_schema(self) -> None:
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS symbols (
                symbol TEXT PRIMARY KEY,
                name TEXT DEFAULT '',
                asset_type TEXT DEFAULT 'stock',
                source TEXT DEFAULT 'yahoo',
                is_active INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS data_sources (
                name TEXT PRIMARY KEY,
                enabled INTEGER DEFAULT 1,
                rate_limit INTEGER DEFAULT 1000,
                api_key TEXT DEFAULT '',
                timeout INTEGER DEFAULT 30,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ohlcv (
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume INTEGER NOT NULL,
                source TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (symbol, timestamp, source),
                FOREIGN KEY (symbol) REFERENCES symbols(symbol)
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol
            ON ohlcv(symbol)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_timestamp
            ON ohlcv(timestamp)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ohlcv_symbol_timestamp
            ON ohlcv(symbol, timestamp DESC)
        """)

        self.conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "MarketDataStorage":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def upsert_ohlcv(self, data: MarketData) -> bool:
        """Insert or update an OHLCV record.

        Args:
            data: MarketData record to upsert.

        Returns:
            True if successful.
        """
        import json

        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()

        cursor.execute(
            """
            INSERT INTO ohlcv (symbol, timestamp, open, high, low, close, volume, source, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, timestamp, source) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                metadata = excluded.metadata,
                created_at = excluded.created_at
            """,
            (
                data.symbol,
                data.timestamp.isoformat(),
                data.open,
                data.high,
                data.low,
                data.close,
                data.volume,
                data.source.value,
                json.dumps(data.metadata),
                now,
            ),
        )
        self.conn.commit()
        return True

    def upsert_ohlcv_batch(self, records: List[MarketData]) -> int:
        """Insert or update multiple OHLCV records in a single transaction.

        Args:
            records: List of MarketData records to upsert.

        Returns:
            Number of records upserted.
        """
        import json

        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()

        try:
            cursor.executemany(
                """
                INSERT INTO ohlcv (symbol, timestamp, open, high, low, close, volume, source, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, timestamp, source) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume,
                    metadata = excluded.metadata,
                    created_at = excluded.created_at
                """,
                [
                    (
                        r.symbol,
                        r.timestamp.isoformat(),
                        r.open,
                        r.high,
                        r.low,
                        r.close,
                        r.volume,
                        r.source.value,
                        json.dumps(r.metadata),
                        now,
                    )
                    for r in records
                ],
            )
            self.conn.commit()
            return len(records)
        except sqlite3.Error:
            self.conn.rollback()
            raise

    def upsert_symbol(self, symbol: Symbol) -> bool:
        """Insert or update a symbol record.

        Args:
            symbol: Symbol record to upsert.

        Returns:
            True if successful.
        """
        now = datetime.utcnow().isoformat()

        self.conn.execute(
            """
            INSERT INTO symbols (symbol, name, asset_type, source, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = excluded.name,
                asset_type = excluded.asset_type,
                source = excluded.source,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (
                symbol.symbol,
                symbol.name,
                symbol.asset_type,
                symbol.source.value,
                1 if symbol.is_active else 0,
                now,
                now,
            ),
        )
        self.conn.commit()
        return True

    def upsert_data_source(
        self,
        name: str,
        enabled: bool = True,
        rate_limit: int = 1000,
        api_key: str = "",
        timeout: int = 30,
    ) -> bool:
        """Insert or update a data source record."""
        now = datetime.utcnow().isoformat()

        self.conn.execute(
            """
            INSERT INTO data_sources (name, enabled, rate_limit, api_key, timeout, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                enabled = excluded.enabled,
                rate_limit = excluded.rate_limit,
                api_key = excluded.api_key,
                timeout = excluded.timeout,
                updated_at = excluded.updated_at
            """,
            (name, 1 if enabled else 0, rate_limit, api_key, timeout, now, now),
        )
        self.conn.commit()
        return True

    def get_latest(self, symbol: str, source: Optional[DataSource] = None) -> Optional[MarketData]:
        """Get the most recent data point for a symbol.

        Args:
            symbol: Ticker symbol to query.
            source: Optional filter by data source.

        Returns:
            Most recent MarketData or None if no data exists.
        """
        import json

        query = "SELECT * FROM ohlcv WHERE symbol = ?"
        params: List[Any] = [symbol]

        if source is not None:
            query += " AND source = ?"
            params.append(source.value)

        query += " ORDER BY timestamp DESC LIMIT 1"

        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()

        if row is None:
            return None

        return MarketData(
            symbol=row["symbol"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            open=row["open"],
            high=row["high"],
            low=row["low"],
            close=row["close"],
            volume=row["volume"],
            source=DataSource(row["source"]),
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
        )

    def get_history(
        self,
        symbol: str,
        days: int = 365,
        source: Optional[DataSource] = None,
    ) -> pd.DataFrame:
        """Get historical data for a symbol as a DataFrame.

        Args:
            symbol: Ticker symbol to query.
            days: Number of days of history to retrieve.
            source: Optional filter by data source.

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume, source.
        """
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        query = "SELECT * FROM ohlcv WHERE symbol = ? AND timestamp >= ?"
        params: List[Any] = [symbol, cutoff]

        if source is not None:
            query += " AND source = ?"
            params.append(source.value)

        query += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, self.conn, params=params)

        if not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"])

        return df

    def list_symbols(self, active_only: bool = True) -> List[Symbol]:
        """List all tracked symbols.

        Args:
            active_only: If True, only return active symbols.

        Returns:
            List of Symbol records.
        """
        query = "SELECT * FROM symbols"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY symbol"

        cursor = self.conn.execute(query)
        rows = cursor.fetchall()

        return [
            Symbol(
                symbol=row["symbol"],
                name=row["name"],
                asset_type=row["asset_type"],
                source=DataSource(row["source"]),
                is_active=bool(row["is_active"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
            for row in rows
        ]

    def symbol_exists(self, symbol: str) -> bool:
        """Check if a symbol is tracked."""
        cursor = self.conn.execute(
            "SELECT 1 FROM symbols WHERE symbol = ?", (symbol,)
        )
        return cursor.fetchone() is not None

    def get_record_count(self, symbol: Optional[str] = None, source: Optional[DataSource] = None) -> int:
        """Get the number of OHLCV records, optionally filtered."""
        query = "SELECT COUNT(*) as cnt FROM ohlcv WHERE 1=1"
        params: List[Any] = []

        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if source is not None:
            query += " AND source = ?"
            params.append(source.value)

        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()
        return row["cnt"] if row else 0

    def get_date_range(
        self, symbol: str, source: Optional[DataSource] = None
    ) -> Optional[Tuple[datetime, datetime]]:
        """Get the date range of available data for a symbol."""
        query = "SELECT MIN(timestamp) as min_ts, MAX(timestamp) as max_ts FROM ohlcv WHERE symbol = ?"
        params: List[Any] = [symbol]

        if source is not None:
            query += " AND source = ?"
            params.append(source.value)

        cursor = self.conn.execute(query, params)
        row = cursor.fetchone()

        if row and row["min_ts"] and row["max_ts"]:
            return (
                datetime.fromisoformat(row["min_ts"]),
                datetime.fromisoformat(row["max_ts"]),
            )
        return None
