"""Reddit collector for financial sentiment signals.

Fetches posts and comments from financial subreddits
(r/wallstreetbets, r/stocks, r/cryptocurrency) using PRAW
with anonymous RSS fallback.
"""

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from src.data.sentiment.models import SentimentSignal, SentimentSource
from src.data.sentiment.sources.rss import _detect_symbols

logger = logging.getLogger(__name__)

# Financial subreddits to monitor
DEFAULT_SUBREDDITS: List[str] = [
    "wallstreetbets",
    "stocks",
    "cryptocurrency",
    "CryptoMarkets",
    "investing",
]

# Reddit RSS URLs for anonymous access
REDDIT_RSS_BASE = "https://www.reddit.com"


class RedditCollector:
    """Collects financial sentiment signals from Reddit.

    Uses PRAW for authenticated access when credentials are available,
    falls back to RSS for anonymous access.
    """

    def __init__(
        self,
        subreddits: Optional[List[str]] = None,
        client_id: str = "",
        client_secret: str = "",
        user_agent: str = "TradingBot/1.0",
        max_age_hours: int = 48,
    ) -> None:
        """Initialize the Reddit collector.

        Args:
            subreddits: List of subreddit names to monitor.
            client_id: Reddit API client ID (for PRAW).
            client_secret: Reddit API client secret (for PRAW).
            user_agent: User agent string for Reddit API.
            max_age_hours: Maximum post age in hours to include.
        """
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_agent = user_agent
        self.max_age_hours = max_age_hours
        self._praw_reddit: Optional[object] = None

    def _get_praw_reddit(self) -> Optional[object]:
        """Get PRAW Reddit instance if credentials are available."""
        if self._praw_reddit is not None:
            return self._praw_reddit

        if not self.client_id or not self.client_secret:
            return None

        try:
            import praw

            self._praw_reddit = praw.Reddit(
                client_id=self.client_id,
                client_secret=self.client_secret,
                user_agent=self.user_agent,
            )
            logger.info("PRAW Reddit client initialized")
            return self._praw_reddit
        except ImportError:
            logger.warning("praw not installed, using RSS fallback")
            return None
        except Exception as e:
            logger.warning("Failed to init PRAW: %s", e)
            return None

    def collect(
        self,
        symbols: Optional[List[str]] = None,
        max_posts_per_sub: int = 50,
        include_comments: bool = False,
    ) -> List[SentimentSignal]:
        """Collect posts from all configured subreddits.

        Args:
            symbols: Optional list of symbols to filter for.
            max_posts_per_sub: Max posts to fetch per subreddit.
            include_comments: Whether to also fetch top comments.

        Returns:
            List of SentimentSignal objects.
        """
        all_signals: List[SentimentSignal] = []

        for subreddit in self.subreddits:
            try:
                signals = self._collect_subreddit(
                    subreddit, symbols, max_posts_per_sub
                )
                all_signals.extend(signals)
                logger.info(
                    "Collected %d posts from r/%s", len(signals), subreddit
                )
            except Exception as e:
                logger.warning("Failed to collect from r/%s: %s", subreddit, e)

            time.sleep(1.0)  # Rate limiting

        return all_signals

    def _collect_subreddit(
        self,
        subreddit: str,
        symbols: Optional[List[str]],
        max_posts: int,
    ) -> List[SentimentSignal]:
        """Collect posts from a single subreddit.

        Tries PRAW first, falls back to RSS.
        """
        praw_reddit = self._get_praw_reddit()
        if praw_reddit is not None:
            return self._collect_with_praw(
                praw_reddit, subreddit, symbols, max_posts
            )
        return self._collect_with_rss(subreddit, symbols, max_posts)

    def _collect_with_praw(
        self,
        praw_reddit: object,
        subreddit: str,
        symbols: Optional[List[str]],
        max_posts: int,
    ) -> List[SentimentSignal]:
        """Collect posts using PRAW."""
        # Type ignore because praw_reddit is object but acts as praw.Reddit
        sub = praw_reddit.subreddit(subreddit)  # type: ignore[union-attr,attr-defined]
        signals: List[SentimentSignal] = []

        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

        for post in sub.hot(limit=max_posts):
            try:
                post_time = datetime.fromtimestamp(
                    post.created_utc, tz=timezone.utc
                )
                if post_time < cutoff:
                    continue

                text = f"{post.title} {post.selftext}"
                detected_symbols = _detect_symbols(text)

                if symbols:
                    symbol_set = {s.upper() for s in symbols}
                    matched = [s for s in detected_symbols if s in symbol_set]
                    if not matched:
                        continue
                    target_symbols = matched
                else:
                    target_symbols = detected_symbols if detected_symbols else ["MARKET"]

                engagement = post.score + post.num_comments
                url = f"https://reddit.com{post.permalink}"

                for sym in target_symbols:
                    signal = SentimentSignal(
                        source=SentimentSource.REDDIT,
                        symbol=sym,
                        timestamp=post_time,
                        headline=post.title[:500],
                        body=post.selftext[:2000] if post.selftext else "",
                        url=url,
                        author=str(post.author) if post.author else "[deleted]",
                        engagement=engagement,
                        source_name=f"r/{subreddit}",
                    )
                    signals.append(signal)

            except Exception as e:
                logger.debug("Failed to parse Reddit post: %s", e)
                continue

        return signals

    def _collect_with_rss(
        self,
        subreddit: str,
        symbols: Optional[List[str]],
        max_posts: int,
    ) -> List[SentimentSignal]:
        """Collect posts using Reddit RSS (anonymous access)."""
        import feedparser

        rss_url = f"{REDDIT_RSS_BASE}/r/{subreddit}/hot.rss?limit={max_posts}"
        feed = feedparser.parse(
            rss_url, request_headers={"User-Agent": self.user_agent}
        )
        signals: List[SentimentSignal] = []
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.max_age_hours)

        for entry in feed.entries[:max_posts]:
            try:
                # Parse published date
                pub_date = datetime.now(timezone.utc)
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        tp = entry.published_parsed
                        pub_date = datetime(
                            tp[0], tp[1], tp[2],
                            tp[3], tp[4], tp[5],
                            tzinfo=timezone.utc,
                        )
                    except (TypeError, ValueError):
                        pass

                if pub_date < cutoff:
                    continue

                title = entry.get("title", "").strip()
                if not title:
                    continue

                body = entry.get("summary", "")
                # Clean HTML
                body = re.sub(r"<[^>]+>", "", body).strip()[:2000]
                url = entry.get("link", "")
                author = entry.get("author", f"r/{subreddit}")

                text = f"{title} {body}"
                detected_symbols = _detect_symbols(text)

                if symbols:
                    symbol_set = {s.upper() for s in symbols}
                    matched = [s for s in detected_symbols if s in symbol_set]
                    if not matched:
                        continue
                    target_symbols = matched
                else:
                    target_symbols = (
                        detected_symbols if detected_symbols else ["MARKET"]
                    )

                for sym in target_symbols:
                    signal = SentimentSignal(
                        source=SentimentSource.REDDIT,
                        symbol=sym,
                        timestamp=pub_date,
                        headline=title[:500],
                        body=body,
                        url=url,
                        author=author,
                        source_name=f"r/{subreddit}",
                    )
                    signals.append(signal)

            except Exception as e:
                logger.debug("Failed to parse RSS entry: %s", e)
                continue

        return signals
