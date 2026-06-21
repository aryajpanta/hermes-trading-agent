"""Data models for the Sentiment Collection System.

Defines the core SentimentSignal dataclass and related enums
for financial news and social media sentiment analysis.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class SentimentSource(str, Enum):
    """Supported sentiment data sources."""

    NEWS_RSS = "news_rss"
    REDDIT = "reddit"
    TWITTER = "twitter"
    SEC = "sec"


@dataclass
class SentimentSignal:
    """A single sentiment signal from any source.

    Attributes:
        source: Origin of the signal (news_rss, reddit, twitter, sec).
        symbol: Ticker symbol or "MARKET" for general market sentiment.
        timestamp: When the signal was published/discovered.
        headline: Title or headline text.
        body: Full article/post body text.
        sentiment_score: Sentiment from -1.0 (bearish) to +1.0 (bullish).
        confidence: Model confidence from 0.0 to 1.0.
        url: Source URL of the article/post.
        author: Author name or username.
        engagement: Engagement metric (upvotes, retweets, etc.).
        source_name: Human-readable source name (e.g., "Reuters", "r/wallstreetbets").
        dedup_key: Key used for deduplication.
    """

    source: SentimentSource
    symbol: str
    timestamp: datetime
    headline: str
    body: str
    sentiment_score: float = 0.0
    confidence: float = 0.0
    url: str = ""
    author: str = ""
    engagement: int = 0
    source_name: str = ""
    dedup_key: str = ""

    def __post_init__(self) -> None:
        """Validate score ranges after initialization."""
        self.sentiment_score = max(-1.0, min(1.0, self.sentiment_score))
        self.confidence = max(0.0, min(1.0, self.confidence))
        self.engagement = max(0, self.engagement)
        if not self.dedup_key:
            self.dedup_key = self._compute_dedup_key()

    def _compute_dedup_key(self) -> str:
        """Compute a deduplication key from URL and normalized headline."""
        import hashlib

        key_parts = [self.url.lower().strip()]
        # Normalize headline: lowercase, remove common variations
        normalized = self.headline.lower().strip()
        key_parts.append(normalized)
        raw = "|".join(key_parts)
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        d["source"] = self.source.value
        d["timestamp"] = self.timestamp.isoformat()
        return d

    @property
    def is_bullish(self) -> bool:
        """Check if signal is bullish."""
        return self.sentiment_score > 0.1

    @property
    def is_bearish(self) -> bool:
        """Check if signal is bearish."""
        return self.sentiment_score < -0.1

    @property
    def is_neutral(self) -> bool:
        """Check if signal is neutral."""
        return -0.1 <= self.sentiment_score <= 0.1


@dataclass
class SentimentAggregate:
    """Aggregated sentiment across multiple signals for a symbol.

    Attributes:
        symbol: The ticker symbol.
        mean_score: Weighted mean sentiment score.
        signal_count: Number of signals included.
        bullish_count: Count of bullish signals.
        bearish_count: Count of bearish signals.
        neutral_count: Count of neutral signals.
        confidence: Overall confidence (mean of individual confidences).
        sources_breakdown: Sentiment by source type.
        latest_signal: Timestamp of most recent signal.
        engagement_total: Sum of all engagement metrics.
    """

    symbol: str
    mean_score: float = 0.0
    signal_count: int = 0
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    confidence: float = 0.0
    sources_breakdown: Dict[str, float] = field(default_factory=dict)
    latest_signal: Optional[datetime] = None
    engagement_total: int = 0

    @property
    def sentiment_label(self) -> str:
        """Human-readable sentiment label."""
        if self.mean_score > 0.3:
            return "STRONG_BULLISH"
        if self.mean_score > 0.1:
            return "BULLISH"
        if self.mean_score < -0.3:
            return "STRONG_BEARISH"
        if self.mean_score < -0.1:
            return "BEARISH"
        return "NEUTRAL"
