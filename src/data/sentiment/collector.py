"""Sentiment collector - orchestrates news and social media collection.

This is the main entry point for collecting sentiment signals from
multiple sources, scoring them, deduplicating, and storing results.
"""

import hashlib
import logging
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

from src.data.sentiment.models import SentimentAggregate, SentimentSignal, SentimentSource
from src.data.sentiment.scorer import score_sentiment, get_available_models
from src.data.sentiment.sources.rss import RSSFeedCollector
from src.data.sentiment.sources.reddit import RedditCollector

logger = logging.getLogger(__name__)


class SentimentStorage:
    """SQLite storage for sentiment signals and aggregates."""

    def __init__(self, db_path: str = "data/sentiment.db") -> None:
        """Initialize sentiment storage.

        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        cursor = self._conn.cursor()
        cursor.executescript("""
            CREATE TABLE IF NOT EXISTS sentiment_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                headline TEXT NOT NULL,
                body TEXT DEFAULT '',
                sentiment_score REAL DEFAULT 0.0,
                confidence REAL DEFAULT 0.0,
                url TEXT DEFAULT '',
                author TEXT DEFAULT '',
                engagement INTEGER DEFAULT 0,
                source_name TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_symbol ON sentiment_signals(symbol);
            CREATE INDEX IF NOT EXISTS idx_timestamp ON sentiment_signals(timestamp);
            CREATE INDEX IF NOT EXISTS idx_dedup ON sentiment_signals(dedup_key);
        """)
        self._conn.commit()

    def store_signal(self, signal: SentimentSignal) -> bool:
        """Store a sentiment signal (deduplicates by key).

        Returns:
            True if stored, False if duplicate.
        """
        try:
            cursor = self._conn.cursor()
            cursor.execute(
                """INSERT OR IGNORE INTO sentiment_signals
                   (dedup_key, source, symbol, timestamp, headline, body,
                    sentiment_score, confidence, url, author, engagement, source_name)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    signal.dedup_key,
                    signal.source.value,
                    signal.symbol,
                    signal.timestamp.isoformat(),
                    signal.headline,
                    signal.body,
                    signal.sentiment_score,
                    signal.confidence,
                    signal.url,
                    signal.author,
                    signal.engagement,
                    signal.source_name,
                ),
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except sqlite3.Error as e:
            logger.error("Failed to store signal: %s", e)
            return False

    def store_signals(self, signals: List[SentimentSignal]) -> int:
        """Store multiple signals. Returns count of new (non-duplicate) signals."""
        count = 0
        for signal in signals:
            if self.store_signal(signal):
                count += 1
        return count

    def get_signals(
        self,
        symbol: str,
        hours: int = 24,
        source: Optional[SentimentSource] = None,
    ) -> List[SentimentSignal]:
        """Get recent signals for a symbol.

        Args:
            symbol: Ticker symbol to filter.
            hours: Number of hours of history.
            source: Optional source filter.

        Returns:
            List of SentimentSignal objects.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        cursor = self._conn.cursor()

        if source:
            cursor.execute(
                """SELECT * FROM sentiment_signals
                   WHERE symbol = ? AND timestamp >= ? AND source = ?
                   ORDER BY timestamp DESC""",
                (symbol, cutoff.isoformat(), source.value),
            )
        else:
            cursor.execute(
                """SELECT * FROM sentiment_signals
                   WHERE symbol = ? AND timestamp >= ?
                   ORDER BY timestamp DESC""",
                (symbol, cutoff.isoformat()),
            )

        rows = cursor.fetchall()
        return [self._row_to_signal(row) for row in rows]

    def get_aggregate(self, symbol: str, hours: int = 24) -> SentimentAggregate:
        """Compute aggregate sentiment for a symbol.

        Uses engagement-weighted scoring.
        """
        signals = self.get_signals(symbol, hours)
        if not signals:
            return SentimentAggregate(symbol=symbol)

        # Engagement-weighted average
        total_engagement = sum(s.engagement for s in signals)
        if total_engagement == 0:
            # No engagement data - use simple average
            mean_score = sum(s.sentiment_score for s in signals) / len(signals)
        else:
            weighted_sum = sum(
                s.sentiment_score * (1 + s.engagement) for s in signals
            )
            weight_total = sum(1 + s.engagement for s in signals)
            mean_score = weighted_sum / weight_total if weight_total > 0 else 0.0

        confidence = sum(s.confidence for s in signals) / len(signals)
        bullish = sum(1 for s in signals if s.is_bullish)
        bearish = sum(1 for s in signals if s.is_bearish)
        neutral = sum(1 for s in signals if s.is_neutral)

        # Source breakdown
        source_scores: Dict[str, List[float]] = {}
        for s in signals:
            src = s.source.value
            if src not in source_scores:
                source_scores[src] = []
            source_scores[src].append(s.sentiment_score)
        sources_breakdown = {
            src: sum(scores) / len(scores) if scores else 0.0
            for src, scores in source_scores.items()
        }

        latest = max(s.timestamp for s in signals)

        return SentimentAggregate(
            symbol=symbol,
            mean_score=round(mean_score, 4),
            signal_count=len(signals),
            bullish_count=bullish,
            bearish_count=bearish,
            neutral_count=neutral,
            confidence=round(confidence, 4),
            sources_breakdown=sources_breakdown,
            latest_signal=latest,
            engagement_total=total_engagement,
        )

    def _row_to_signal(self, row: sqlite3.Row) -> SentimentSignal:
        """Convert a database row to SentimentSignal."""
        source_val = row["source"]
        source_enum = SentimentSource(source_val)
        ts = datetime.fromisoformat(row["timestamp"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        return SentimentSignal(
            source=source_enum,
            symbol=row["symbol"],
            timestamp=ts,
            headline=row["headline"],
            body=row["body"],
            sentiment_score=row["sentiment_score"],
            confidence=row["confidence"],
            url=row["url"],
            author=row["author"],
            engagement=row["engagement"],
            source_name=row["source_name"],
            dedup_key=row["dedup_key"],
        )

    def to_dataframe(
        self, symbol: str, hours: int = 24
    ) -> pd.DataFrame:
        """Get signals as a pandas DataFrame."""
        signals = self.get_signals(symbol, hours)
        if not signals:
            return pd.DataFrame()
        data = [s.to_dict() for s in signals]
        return pd.DataFrame(data)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()


class SentimentCollector:
    """Orchestrates sentiment collection from multiple sources.

    Manages RSS feeds, Reddit, and sentiment scoring.
    Handles deduplication and engagement-weighted aggregation.
    """

    def __init__(
        self,
        storage_path: str = "data/sentiment.db",
        rss_feeds: Optional[Dict[str, str]] = None,
        reddit_subreddits: Optional[List[str]] = None,
        reddit_client_id: str = "",
        reddit_client_secret: str = "",
        sentiment_model: str = "auto",
    ) -> None:
        """Initialize the sentiment collector.

        Args:
            storage_path: Path to SQLite database.
            rss_feeds: Custom RSS feeds. Uses defaults if None.
            reddit_subreddits: Custom subreddits. Uses defaults if None.
            reddit_client_id: Reddit API client ID.
            reddit_client_secret: Reddit API client secret.
            sentiment_model: Model to use ("auto", "finbert", "vader").
        """
        self.storage = SentimentStorage(storage_path)
        self.rss_collector = RSSFeedCollector(feeds=rss_feeds)
        self.reddit_collector = RedditCollector(
            subreddits=reddit_subreddits,
            client_id=reddit_client_id,
            client_secret=reddit_client_secret,
        )
        self.sentiment_model = sentiment_model

    def collect_news(
        self, symbols: List[str], max_articles_per_feed: int = 50
    ) -> List[SentimentSignal]:
        """Collect and score news articles for given symbols.

        Args:
            symbols: List of ticker symbols.
            max_articles_per_feed: Max articles per RSS feed.

        Returns:
            List of scored SentimentSignal objects.
        """
        logger.info("Collecting news for symbols: %s", symbols)
        raw_signals = self.rss_collector.collect(
            symbols=symbols, max_articles_per_feed=max_articles_per_feed
        )

        # Score sentiment
        scored = self._score_signals(raw_signals)

        # Deduplicate and store
        new_count = self.storage.store_signals(scored)
        logger.info("Stored %d new signals (from %d total)", new_count, len(scored))

        return scored

    def collect_social(
        self,
        symbols: List[str],
        max_posts_per_sub: int = 50,
    ) -> List[SentimentSignal]:
        """Collect and score social media signals.

        Args:
            symbols: List of ticker symbols.
            max_posts_per_sub: Max posts per subreddit.

        Returns:
            List of scored SentimentSignal objects.
        """
        logger.info("Collecting social signals for symbols: %s", symbols)
        raw_signals = self.reddit_collector.collect(
            symbols=symbols, max_posts_per_sub=max_posts_per_sub
        )

        # Score sentiment
        scored = self._score_signals(raw_signals)

        # Deduplicate and store
        new_count = self.storage.store_signals(scored)
        logger.info("Stored %d new social signals", new_count)

        return scored

    def collect_all(
        self, symbols: List[str], hours: int = 24
    ) -> List[SentimentSignal]:
        """Collect from all sources for given symbols.

        Args:
            symbols: List of ticker symbols.
            hours: Not used for collection (used for history queries).

        Returns:
            List of scored SentimentSignal objects from all sources.
        """
        all_signals: List[SentimentSignal] = []
        all_signals.extend(self.collect_news(symbols))
        all_signals.extend(self.collect_social(symbols))
        return all_signals

    def score_sentiment(self, text: str) -> Tuple[float, float]:
        """Score sentiment for a piece of text.

        Args:
            text: Text to analyze.

        Returns:
            Tuple of (sentiment_score, confidence).
        """
        return score_sentiment(text, model=self.sentiment_model)

    def get_sentiment_history(
        self, symbol: str, hours: int = 24
    ) -> pd.DataFrame:
        """Get recent sentiment history as a DataFrame.

        Args:
            symbol: Ticker symbol.
            hours: Number of hours of history.

        Returns:
            DataFrame with sentiment history.
        """
        return self.storage.to_dataframe(symbol, hours)

    def get_aggregate_sentiment(
        self, symbol: str, hours: int = 24
    ) -> SentimentAggregate:
        """Get aggregate sentiment for a symbol.

        Args:
            symbol: Ticker symbol.
            hours: Number of hours to aggregate.

        Returns:
            SentimentAggregate with weighted scores.
        """
        return self.storage.get_aggregate(symbol, hours)

    def deduplicate(self, signals: List[SentimentSignal]) -> List[SentimentSignal]:
        """Remove duplicate signals based on dedup keys.

        When the same story appears from multiple sources, keep the one
        with highest engagement.

        Args:
            signals: List of signals to deduplicate.

        Returns:
            Deduplicated list, keeping highest engagement per story.
        """
        seen: Dict[str, SentimentSignal] = {}
        for signal in signals:
            key = signal.dedup_key
            if key not in seen:
                seen[key] = signal
            elif signal.engagement > seen[key].engagement:
                seen[key] = signal
        return list(seen.values())

    def _score_signals(self, signals: List[SentimentSignal]) -> List[SentimentSignal]:
        """Score sentiment for a batch of signals.

        Args:
            signals: List of unscored signals.

        Returns:
            List of signals with sentiment scores populated.
        """
        for signal in signals:
            # Combine headline and body for scoring
            text = f"{signal.headline}. {signal.body}" if signal.body else signal.headline
            try:
                score, confidence = score_sentiment(text, model=self.sentiment_model)
                signal.sentiment_score = score
                signal.confidence = confidence
            except Exception as e:
                logger.warning("Failed to score sentiment: %s", e)
                signal.sentiment_score = 0.0
                signal.confidence = 0.0

        return signals

    def get_available_models(self) -> Dict[str, bool]:
        """Check which sentiment models are available.

        Returns:
            Dictionary of model availability.
        """
        return get_available_models()

    def close(self) -> None:
        """Close all connections."""
        self.storage.close()
