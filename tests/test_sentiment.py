"""Tests for the Sentiment Collection System.

Tests cover: models, scorer (VADER), RSS collector, Reddit collector,
deduplication, storage, aggregation, and the main collector.
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from src.data.sentiment.models import SentimentSignal, SentimentSource, SentimentAggregate
from src.data.sentiment.scorer import (
    score_sentiment,
    score_with_vader,
    batch_score_sentiment,
    get_available_models,
)
from src.data.sentiment.collector import SentimentCollector, SentimentStorage
from src.data.sentiment.sources.rss import (
    _clean_html,
    _detect_symbols,
    RSSFeedCollector,
)
from src.data.sentiment.sources.reddit import RedditCollector


# ============================================================
# Model Tests
# ============================================================


class TestSentimentSignal:
    """Tests for the SentimentSignal dataclass."""

    def test_basic_creation(self) -> None:
        """Test creating a basic SentimentSignal."""
        now = datetime.now(timezone.utc)
        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Reports Record Earnings",
            body="Apple Inc. reported record quarterly earnings.",
            sentiment_score=0.75,
            confidence=0.85,
            url="https://example.com/article",
            author="Reuters",
            engagement=150,
            source_name="Reuters",
        )
        assert signal.source == SentimentSource.NEWS_RSS
        assert signal.symbol == "AAPL"
        assert signal.sentiment_score == 0.75
        assert signal.confidence == 0.85
        assert signal.engagement == 150

    def test_score_clamping(self) -> None:
        """Test that scores are clamped to valid range."""
        now = datetime.now(timezone.utc)
        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="TEST",
            timestamp=now,
            headline="Test",
            body="",
            sentiment_score=1.5,  # Out of range
            confidence=-0.3,  # Out of range
        )
        assert signal.sentiment_score == 1.0
        assert signal.confidence == 0.0

    def test_engagement_clamping(self) -> None:
        """Test that negative engagement is clamped to 0."""
        now = datetime.now(timezone.utc)
        signal = SentimentSignal(
            source=SentimentSource.REDDIT,
            symbol="TEST",
            timestamp=now,
            headline="Test",
            body="",
            engagement=-10,
        )
        assert signal.engagement == 0

    def test_auto_dedup_key(self) -> None:
        """Test that dedup_key is auto-generated."""
        now = datetime.now(timezone.utc)
        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",
            body="",
            url="https://example.com/article1",
        )
        assert signal.dedup_key != ""
        assert len(signal.dedup_key) == 32  # MD5 hex digest

    def test_same_content_same_key(self) -> None:
        """Test that same content produces same dedup key."""
        now = datetime.now(timezone.utc)
        sig1 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",
            body="",
            url="https://example.com/article1",
        )
        sig2 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",
            body="",
            url="https://example.com/article1",
        )
        assert sig1.dedup_key == sig2.dedup_key

    def test_different_content_different_key(self) -> None:
        """Test that different content produces different dedup keys."""
        now = datetime.now(timezone.utc)
        sig1 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",
            body="",
            url="https://example.com/article1",
        )
        sig2 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Misses Estimates",
            body="",
            url="https://example.com/article2",
        )
        assert sig1.dedup_key != sig2.dedup_key

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        now = datetime.now(timezone.utc)
        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Test Article",
            body="Test body",
            sentiment_score=0.5,
        )
        d = signal.to_dict()
        assert d["source"] == "news_rss"
        assert d["symbol"] == "AAPL"
        assert isinstance(d["timestamp"], str)

    def test_is_bullish(self) -> None:
        """Test bullish detection."""
        now = datetime.now(timezone.utc)
        bullish = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="TEST",
            timestamp=now,
            headline="Test",
            body="",
            sentiment_score=0.5,
        )
        assert bullish.is_bullish is True
        assert bullish.is_bearish is False
        assert bullish.is_neutral is False

    def test_is_bearish(self) -> None:
        """Test bearish detection."""
        now = datetime.now(timezone.utc)
        bearish = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="TEST",
            timestamp=now,
            headline="Test",
            body="",
            sentiment_score=-0.5,
        )
        assert bearish.is_bearish is True
        assert bearish.is_bullish is False
        assert bearish.is_neutral is False

    def test_is_neutral(self) -> None:
        """Test neutral detection."""
        now = datetime.now(timezone.utc)
        neutral = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="TEST",
            timestamp=now,
            headline="Test",
            body="",
            sentiment_score=0.0,
        )
        assert neutral.is_neutral is True
        assert neutral.is_bullish is False
        assert neutral.is_bearish is False


class TestSentimentAggregate:
    """Tests for the SentimentAggregate dataclass."""

    def test_sentiment_label_strong_bullish(self) -> None:
        agg = SentimentAggregate(symbol="TEST", mean_score=0.5)
        assert agg.sentiment_label == "STRONG_BULLISH"

    def test_sentiment_label_bullish(self) -> None:
        agg = SentimentAggregate(symbol="TEST", mean_score=0.2)
        assert agg.sentiment_label == "BULLISH"

    def test_sentiment_label_neutral(self) -> None:
        agg = SentimentAggregate(symbol="TEST", mean_score=0.05)
        assert agg.sentiment_label == "NEUTRAL"

    def test_sentiment_label_bearish(self) -> None:
        agg = SentimentAggregate(symbol="TEST", mean_score=-0.2)
        assert agg.sentiment_label == "BEARISH"

    def test_sentiment_label_strong_bearish(self) -> None:
        agg = SentimentAggregate(symbol="TEST", mean_score=-0.5)
        assert agg.sentiment_label == "STRONG_BEARISH"


# ============================================================
# Scorer Tests (VADER - always available)
# ============================================================


class TestVADERScorer:
    """Tests for VADER sentiment scoring."""

    def test_positive_sentiment(self) -> None:
        """Test bullish text scores positively."""
        score, confidence = score_with_vader("Stock surges to all-time high on strong earnings!")
        assert score > 0.3, f"Expected positive score, got {score}"
        assert 0.0 <= confidence <= 1.0

    def test_negative_sentiment(self) -> None:
        """Test bearish text scores negatively."""
        score, confidence = score_with_vader("Market crashes amid recession fears and job losses!")
        assert score < -0.3, f"Expected negative score, got {score}"
        assert 0.0 <= confidence <= 1.0

    def test_neutral_sentiment(self) -> None:
        """Test neutral text scores near zero."""
        score, confidence = score_with_vader("The stock closed at $150 per share.")
        assert -0.3 < score < 0.3, f"Expected neutral score, got {score}"

    def test_empty_text_raises(self) -> None:
        """Test that empty text raises ValueError."""
        with pytest.raises(ValueError, match="empty text"):
            score_sentiment("")

    def test_whitespace_only_raises(self) -> None:
        """Test that whitespace-only text raises ValueError."""
        with pytest.raises(ValueError, match="empty text"):
            score_sentiment("   ")

    def test_auto_model_uses_vader(self) -> None:
        """Test that auto model works (falls back to VADER if no FinBERT)."""
        score, confidence = score_sentiment("Great earnings report!", model="auto")
        assert -1.0 <= score <= 1.0
        assert 0.0 <= confidence <= 1.0

    def test_explicit_vader(self) -> None:
        """Test explicit VADER model selection."""
        score, confidence = score_sentiment("Terrible losses!", model="vader")
        assert score < 0

    def test_batch_scoring(self) -> None:
        """Test batch sentiment scoring."""
        texts = [
            "Incredible amazing fantastic stock soars to record high!",
            "Market crashes badly!",
            "Trading volume was normal today.",
        ]
        results = batch_score_sentiment(texts, model="vader")
        assert len(results) == 3
        assert results[0][0] > 0  # Positive
        assert results[1][0] < 0  # Negative
        assert -0.5 < results[2][0] < 0.5  # Neutral-ish

    def test_available_models(self) -> None:
        """Test model availability check."""
        models = get_available_models()
        assert "vader" in models
        assert models["vader"] is True


# ============================================================
# RSS Source Tests
# ============================================================


class TestRSSHelpers:
    """Tests for RSS helper functions."""

    def test_clean_html(self) -> None:
        """Test HTML tag removal."""
        assert _clean_html("<p>Hello <b>world</b></p>") == "Hello world"
        assert _clean_html("<a href='http://x'>link</a>") == "link"
        assert _clean_html("No tags here") == "No tags here"
        assert _clean_html("Extra   spaces") == "Extra spaces"

    def test_detect_ticker_symbol(self) -> None:
        """Test $TICKER pattern detection."""
        symbols = _detect_symbols("Breaking: $AAPL reports record quarter!")
        assert "AAPL" in symbols

    def test_detect_multiple_tickers(self) -> None:
        """Test multiple ticker detection."""
        symbols = _detect_symbols("Watch $AAPL and $MSFT today!")
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_detect_crypto_name(self) -> None:
        """Test cryptocurrency name detection."""
        symbols = _detect_symbols("Bitcoin surges past $100,000!")
        assert "BTC" in symbols

    def test_detect_ethereum(self) -> None:
        """Test Ethereum detection."""
        symbols = _detect_symbols("Ethereum staking yields increase!")
        assert "ETH" in symbols

    def test_no_symbols(self) -> None:
        """Test text with no detectable symbols."""
        symbols = _detect_symbols("The market closed mixed today.")
        assert len(symbols) == 0


class TestRSSFeedCollector:
    """Tests for the RSS feed collector."""

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        collector = RSSFeedCollector()
        assert len(collector.feeds) > 0
        assert collector.timeout == 30
        assert collector.max_age_hours == 48

    def test_init_custom_feeds(self) -> None:
        """Test custom feed initialization."""
        custom = {"MyFeed": "https://example.com/rss"}
        collector = RSSFeedCollector(feeds=custom)
        assert collector.feeds == custom

    @patch("src.data.sentiment.sources.rss.feedparser")
    def test_collect_empty_feed(self, mock_feedparser: MagicMock) -> None:
        """Test collecting from an empty feed."""
        mock_feedparser.parse.return_value = MagicMock(entries=[])
        collector = RSSFeedCollector(feeds={"Empty": "https://empty.com/rss"})
        signals = collector.collect()
        assert signals == []

    @patch("src.data.sentiment.sources.rss.feedparser")
    def test_collect_with_entries(self, mock_feedparser: MagicMock) -> None:
        """Test collecting articles with entries."""
        now = datetime.now(timezone.utc)
        mock_entry = {
            "title": "$AAPL Hits Record High on Strong Earnings",
            "summary": "Apple stock surges after earnings beat.",
            "link": "https://example.com/aapl-record",
            "author": "Reuters",
            "published_parsed": now.timetuple(),
        }
        mock_feed = MagicMock()
        mock_feed.entries = [mock_entry]
        mock_feedparser.parse.return_value = mock_feed

        collector = RSSFeedCollector(
            feeds={"TestFeed": "https://test.com/rss"},
            max_age_hours=24,
        )
        signals = collector.collect(symbols=["AAPL"])
        assert len(signals) == 1
        assert signals[0].symbol == "AAPL"
        assert signals[0].source == SentimentSource.NEWS_RSS

    @patch("src.data.sentiment.sources.rss.feedparser")
    def test_collect_filters_by_symbol(self, mock_feedparser: MagicMock) -> None:
        """Test that symbol filtering works."""
        now = datetime.now(timezone.utc)
        mock_entry = {
            "title": "Bitcoin crashes to $50k",
            "summary": "Crypto market sells off.",
            "link": "https://example.com/btc-crash",
            "author": "CoinDesk",
            "published_parsed": now.timetuple(),
        }
        mock_feed = MagicMock()
        mock_feed.entries = [mock_entry]
        mock_feedparser.parse.return_value = mock_feed

        collector = RSSFeedCollector(
            feeds={"Test": "https://test.com/rss"},
            max_age_hours=24,
        )
        # Requesting AAPL but article is about BTC - should get nothing
        signals = collector.collect(symbols=["AAPL"])
        assert len(signals) == 0


# ============================================================
# Reddit Source Tests
# ============================================================


class TestRedditCollector:
    """Tests for the Reddit collector."""

    def test_init_defaults(self) -> None:
        """Test default initialization."""
        collector = RedditCollector()
        assert "wallstreetbets" in collector.subreddits
        assert "stocks" in collector.subreddits

    def test_init_custom_subreddits(self) -> None:
        """Test custom subreddit initialization."""
        collector = RedditCollector(subreddits=["investing", "stocks"])
        assert collector.subreddits == ["investing", "stocks"]

    def test_collect_with_rss_fallback(self) -> None:
        """Test RSS fallback when PRAW credentials not provided."""
        collector = RedditCollector(
            subreddits=["wallstreetbets"],
            max_age_hours=24,
        )
        # Without credentials, should fall back to RSS
        assert collector._get_praw_reddit() is None


# ============================================================
# Storage Tests
# ============================================================


class TestSentimentStorage:
    """Tests for sentiment storage."""

    def test_init_creates_db(self, tmp_path: Path) -> None:
        """Test that initialization creates the database."""
        db_path = str(tmp_path / "test.db")
        storage = SentimentStorage(db_path)
        assert Path(db_path).exists()
        storage.close()

    def test_store_and_retrieve(self, tmp_path: Path) -> None:
        """Test storing and retrieving signals."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",
            body="Record quarter!",
            sentiment_score=0.75,
            confidence=0.85,
            url="https://example.com",
            author="Reuters",
            engagement=100,
            source_name="Reuters",
        )

        # Store
        result = storage.store_signal(signal)
        assert result is True

        # Retrieve
        signals = storage.get_signals("AAPL", hours=1)
        assert len(signals) == 1
        assert signals[0].headline == "Apple Beats Earnings"
        assert signals[0].sentiment_score == 0.75

        storage.close()

    def test_deduplication(self, tmp_path: Path) -> None:
        """Test that duplicate signals are rejected."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Earnings",
            body="",
            sentiment_score=0.5,
            url="https://example.com",
        )

        # Store twice - second should be rejected
        assert storage.store_signal(signal) is True
        assert storage.store_signal(signal) is False  # Duplicate

        signals = storage.get_signals("AAPL", hours=1)
        assert len(signals) == 1
        storage.close()

    def test_store_signals_batch(self, tmp_path: Path) -> None:
        """Test batch signal storage."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        signals = [
            SentimentSignal(
                source=SentimentSource.NEWS_RSS,
                symbol="AAPL",
                timestamp=now,
                headline=f"Article {i}",
                body="",
                sentiment_score=0.1 * i,
            )
            for i in range(5)
        ]

        count = storage.store_signals(signals)
        assert count == 5
        storage.close()

    def test_source_filter(self, tmp_path: Path) -> None:
        """Test filtering by source."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        # Store RSS signal
        rss_signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="RSS Article",
            body="",
        )
        storage.store_signal(rss_signal)

        # Store Reddit signal
        reddit_signal = SentimentSignal(
            source=SentimentSource.REDDIT,
            symbol="AAPL",
            timestamp=now,
            headline="Reddit Post",
            body="",
        )
        storage.store_signal(reddit_signal)

        # Filter by RSS
        rss_only = storage.get_signals("AAPL", hours=1, source=SentimentSource.NEWS_RSS)
        assert len(rss_only) == 1
        assert rss_only[0].source == SentimentSource.NEWS_RSS

        # Filter by Reddit
        reddit_only = storage.get_signals("AAPL", hours=1, source=SentimentSource.REDDIT)
        assert len(reddit_only) == 1
        assert reddit_only[0].source == SentimentSource.REDDIT

        storage.close()

    def test_to_dataframe(self, tmp_path: Path) -> None:
        """Test DataFrame conversion."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Test",
            body="",
            sentiment_score=0.5,
        )
        storage.store_signal(signal)

        df = storage.to_dataframe("AAPL", hours=1)
        assert len(df) == 1
        assert "symbol" in df.columns
        assert "sentiment_score" in df.columns
        storage.close()


# ============================================================
# Aggregation Tests
# ============================================================


class TestSentimentAggregation:

    def test_empty_aggregate(self, tmp_path: Path) -> None:
        """Test aggregate with no data."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        agg = storage.get_aggregate("AAPL", hours=24)
        assert agg.symbol == "AAPL"
        assert agg.signal_count == 0
        assert agg.mean_score == 0.0
        storage.close()

    def test_engagement_weighted(self, tmp_path: Path) -> None:
        """Test engagement-weighted scoring."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        # High engagement bullish signal
        bullish = SentimentSignal(
            source=SentimentSource.REDDIT,
            symbol="AAPL",
            timestamp=now,
            headline="Bullish",
            body="",
            sentiment_score=0.8,
            confidence=0.9,
            engagement=1000,
        )
        storage.store_signal(bullish)

        # Low engagement bearish signal
        bearish = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Bearish",
            body="",
            sentiment_score=-0.6,
            confidence=0.7,
            engagement=10,
        )
        storage.store_signal(bearish)

        agg = storage.get_aggregate("AAPL", hours=1)
        assert agg.symbol == "AAPL"
        assert agg.signal_count == 2
        # Bullish should dominate due to high engagement
        assert agg.mean_score > 0, f"Expected positive weighted score, got {agg.mean_score}"
        assert agg.bullish_count == 1
        assert agg.bearish_count == 1
        assert agg.engagement_total == 1010

        storage.close()

    def test_source_breakdown(self, tmp_path: Path) -> None:
        """Test source-level breakdown in aggregate."""
        storage = SentimentStorage(str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        for i in range(3):
            signal = SentimentSignal(
                source=SentimentSource.NEWS_RSS,
                symbol="AAPL",
                timestamp=now,
                headline=f"News {i}",
                body="",
                sentiment_score=0.5,
                engagement=i * 100,
            )
            storage.store_signal(signal)

        reddit_sig = SentimentSignal(
            source=SentimentSource.REDDIT,
            symbol="AAPL",
            timestamp=now,
            headline="Reddit post",
            body="",
            sentiment_score=-0.3,
            engagement=50,
        )
        storage.store_signal(reddit_sig)

        agg = storage.get_aggregate("AAPL", hours=1)
        assert "news_rss" in agg.sources_breakdown
        assert "reddit" in agg.sources_breakdown
        assert agg.sources_breakdown["news_rss"] > 0
        assert agg.sources_breakdown["reddit"] < 0

        storage.close()


# ============================================================
# Collector Integration Tests
# ============================================================


class TestSentimentCollector:
    """Tests for the main SentimentCollector."""

    def test_init(self, tmp_path: Path) -> None:
        """Test collector initialization."""
        collector = SentimentCollector(storage_path=str(tmp_path / "test.db"))
        assert collector.sentiment_model == "auto"
        collector.close()

    def test_deduplication(self, tmp_path: Path) -> None:
        """Test deduplication logic."""
        collector = SentimentCollector(storage_path=str(tmp_path / "test.db"))
        now = datetime.now(timezone.utc)

        # Same story, different sources
        sig1 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",
            body="",
            url="https://reuters.com/article1",
            engagement=100,
        )
        sig2 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Apple Beats Earnings",  # Same headline
            body="",
            url="https://reuters.com/article1",  # Same URL
            engagement=500,
        )
        sig3 = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Different Story",
            body="",
            url="https://example.com/other",
            engagement=10,
        )

        # Deduplicate - should keep sig2 (higher engagement) and sig3
        deduped = collector.deduplicate([sig1, sig2, sig3])
        assert len(deduped) == 2

        # The one with higher engagement should be kept
        headlines = {s.headline for s in deduped}
        assert "Apple Beats Earnings" in headlines
        assert "Different Story" in headlines

        collector.close()

    def test_score_text(self, tmp_path: Path) -> None:
        """Test direct text scoring."""
        collector = SentimentCollector(
            storage_path=str(tmp_path / "test.db"),
            sentiment_model="vader",
        )
        score, conf = collector.score_sentiment("Incredible amazing fantastic gains!")
        assert score > 0, f"Expected positive score, got {score}"
        assert 0.0 <= conf <= 1.0
        collector.close()

    def test_available_models(self, tmp_path: Path) -> None:
        """Test model availability check."""
        collector = SentimentCollector(storage_path=str(tmp_path / "test.db"))
        models = collector.get_available_models()
        assert "vader" in models
        assert models["vader"] is True
        collector.close()

    def test_get_sentiment_history(self, tmp_path: Path) -> None:
        """Test sentiment history retrieval."""
        storage_path = str(tmp_path / "test.db")
        collector = SentimentCollector(storage_path=storage_path)
        now = datetime.now(timezone.utc)

        # Manually store some signals
        signal = SentimentSignal(
            source=SentimentSource.NEWS_RSS,
            symbol="AAPL",
            timestamp=now,
            headline="Test",
            body="",
            sentiment_score=0.5,
        )
        collector.storage.store_signal(signal)

        df = collector.get_sentiment_history("AAPL", hours=1)
        assert len(df) == 1

        collector.close()

    def test_get_aggregate_sentiment(self, tmp_path: Path) -> None:
        """Test aggregate sentiment retrieval."""
        storage_path = str(tmp_path / "test.db")
        collector = SentimentCollector(storage_path=storage_path)
        now = datetime.now(timezone.utc)

        for i in range(5):
            signal = SentimentSignal(
                source=SentimentSource.NEWS_RSS,
                symbol="AAPL",
                timestamp=now,
                headline=f"Article {i}",
                body="",
                sentiment_score=0.5,
                confidence=0.8,
                engagement=i * 100,
            )
            collector.storage.store_signal(signal)

        agg = collector.get_aggregate_sentiment("AAPL", hours=1)
        assert agg.symbol == "AAPL"
        assert agg.signal_count == 5
        assert agg.confidence > 0

        collector.close()


# ============================================================
# CLI Tests
# ============================================================


class TestCLI:
    """Tests for the CLI module."""

    def test_cli_module_exists(self) -> None:
        """Test that the CLI module can be imported."""
        import src.data.sentiment.__main__  # noqa: F401
