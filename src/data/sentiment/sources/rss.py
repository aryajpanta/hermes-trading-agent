"""RSS feed collector for financial news sentiment.

Fetches articles from RSS feeds (Reuters, MarketWatch, CoinDesk, etc.)
and converts them to SentimentSignal objects.
"""

import hashlib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from email.utils import parsedate_to_datetime

import feedparser

from src.data.sentiment.models import SentimentSignal, SentimentSource

logger = logging.getLogger(__name__)

# Default RSS feeds for financial news
DEFAULT_RSS_FEEDS: Dict[str, str] = {
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Markets": "https://feeds.reuters.com/reuters/marketsNews",
    "MarketWatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Yahoo Finance": "https://finance.yahoo.com/news/rssindex",
    "CNBC": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
}

# Symbol detection patterns
TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")
CRYPTO_NAMES: Dict[str, str] = {
    "bitcoin": "BTC",
    "btc": "BTC",
    "ethereum": "ETH",
    "eth": "ETH",
    "solana": "SOL",
    "sol": "SOL",
    "dogecoin": "DOGE",
    "doge": "DOGE",
    "cardano": "ADA",
    "ada": "ADA",
    "ripple": "XRP",
    "xrp": "XRP",
    "polkadot": "DOT",
    "avalanche": "AVAX",
    "chainlink": "LINK",
}


def _clean_html(text: str) -> str:
    """Remove HTML tags from text."""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip()


def _parse_feed_date(entry: Dict) -> Optional[datetime]:
    """Parse date from a feed entry."""
    for key in ("published_parsed", "updated_parsed"):
        time_struct = entry.get(key)
        if time_struct:
            try:
                dt = datetime(
                    time_struct[0], time_struct[1], time_struct[2],
                    time_struct[3], time_struct[4], time_struct[5],
                    tzinfo=timezone.utc,
                )
                return dt
            except (TypeError, ValueError):
                continue

    for key in ("published", "updated"):
        date_str = entry.get(key)
        if date_str:
            try:
                return parsedate_to_datetime(date_str)
            except (TypeError, ValueError):
                continue

    return datetime.now(timezone.utc)


def _detect_symbols(text: str) -> List[str]:
    """Detect ticker symbols mentioned in text.

    Args:
        text: Text to scan for symbols.

    Returns:
        List of detected symbols (deduplicated).
    """
    symbols: List[str] = []

    # Find $TICKER patterns
    for match in TICKER_PATTERN.finditer(text):
        symbol = match.group(1)
        if symbol not in symbols:
            symbols.append(symbol)

    # Find crypto names
    text_lower = text.lower()
    for name, symbol in CRYPTO_NAMES.items():
        if name in text_lower and symbol not in symbols:
            symbols.append(symbol)

    return symbols


class RSSFeedCollector:
    """Collects financial news from RSS feeds.

    Fetches articles, parses them, and detects relevant symbols.
    """

    def __init__(
        self,
        feeds: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        max_age_hours: int = 48,
    ) -> None:
        """Initialize the RSS feed collector.

        Args:
            feeds: Custom feed name -> URL mapping. Uses defaults if None.
            timeout: HTTP request timeout in seconds.
            max_age_hours: Maximum article age in hours to include.
        """
        self.feeds = feeds or DEFAULT_RSS_FEEDS
        self.timeout = timeout
        self.max_age_hours = max_age_hours

    def collect(
        self,
        symbols: Optional[List[str]] = None,
        max_articles_per_feed: int = 50,
    ) -> List[SentimentSignal]:
        """Collect articles from all configured RSS feeds.

        Args:
            symbols: Optional list of symbols to filter for.
                     If None, returns all articles.
            max_articles_per_feed: Max articles to process per feed.

        Returns:
            List of SentimentSignal objects.
        """
        all_signals: List[SentimentSignal] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

        for feed_name, feed_url in self.feeds.items():
            try:
                signals = self._parse_feed(
                    feed_name, feed_url, symbols, max_articles_per_feed, cutoff
                )
                all_signals.extend(signals)
                logger.info(
                    "Collected %d articles from %s", len(signals), feed_name
                )
            except Exception as e:
                logger.warning("Failed to collect from %s: %s", feed_name, e)

            # Be polite
            time.sleep(0.5)

        return all_signals

    def _parse_feed(
        self,
        feed_name: str,
        feed_url: str,
        symbols: Optional[List[str]],
        max_articles: int,
        cutoff: datetime,
    ) -> List[SentimentSignal]:
        """Parse a single RSS feed.

        Args:
            feed_name: Human-readable feed name.
            feed_url: URL of the RSS feed.
            symbols: Optional symbol filter.
            max_articles: Max articles to process.
            cutoff: Oldest timestamp to include.

        Returns:
            List of SentimentSignal objects from this feed.
        """
        feed = feedparser.parse(feed_url, request_headers={"User-Agent": "TradingBot/1.0"})
        signals: List[SentimentSignal] = []

        for entry in feed.entries[:max_articles]:
            try:
                pub_date = _parse_feed_date(entry)
                if pub_date is None:
                    pub_date = datetime.now(timezone.utc)
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                if pub_date < cutoff:
                    continue

                headline = entry.get("title", "").strip()
                if not headline:
                    continue

                body = _clean_html(
                    entry.get("summary", entry.get("description", ""))
                )
                url = entry.get("link", "")
                author = entry.get("author", feed_name)

                # Detect symbols in headline + body
                text_for_symbols = f"{headline} {body}"
                detected_symbols = _detect_symbols(text_for_symbols)

                # If specific symbols requested, only include matching articles
                if symbols:
                    symbol_set = {s.upper() for s in symbols}
                    matched = [s for s in detected_symbols if s in symbol_set]
                    if not matched:
                        continue
                    for sym in matched:
                        signal = SentimentSignal(
                            source=SentimentSource.NEWS_RSS,
                            symbol=sym,
                            timestamp=pub_date,
                            headline=headline,
                            body=body[:2000],  # Truncate long bodies
                            url=url,
                            author=author,
                            source_name=feed_name,
                        )
                        signals.append(signal)
                else:
                    # No symbol filter - use MARKET for general
                    target_symbols = detected_symbols if detected_symbols else ["MARKET"]
                    for sym in target_symbols:
                        signal = SentimentSignal(
                            source=SentimentSource.NEWS_RSS,
                            symbol=sym,
                            timestamp=pub_date,
                            headline=headline,
                            body=body[:2000],
                            url=url,
                            author=author,
                            source_name=feed_name,
                        )
                        signals.append(signal)

            except Exception as e:
                logger.debug("Failed to parse entry from %s: %s", feed_name, e)
                continue

        return signals
