"""X (Twitter) post scraper for sentiment — credential-free scraping route.

X locked down its official API, so this uses the public **Nitter** front-end's
RSS search endpoint, which needs no login/bearer token. RSS is parsed with the
stdlib XML parser (no feedparser dependency).

Nitter instances come and go, so a list is tried in order and the first one
that returns posts wins. If every instance fails the scraper returns ``[]`` —
the sentiment analyzer then degrades gracefully to news-only.

Configure instances/accounts via env or by passing them in:
    X_NITTER_INSTANCES   comma-separated base URLs (e.g. https://nitter.net)
    X_ACCOUNTS           comma-separated finance handles to also pull from
    ENABLE_X_SENTIMENT   "false" to disable entirely
"""

import json
import logging
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

# Backend: "nitter" (zero-install RSS scrape) or "cli" (agent-reach's
# twitter-cli / opencli, which use cookie auth and are far more reliable).
DEFAULT_BACKEND = "nitter"
# Binary for the cli backend. "twitter" (twitter-cli) or "opencli".
DEFAULT_CLI_BIN = "twitter"

# Nitter mirrors change often — override with X_NITTER_INSTANCES.
DEFAULT_NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
]

# A few high-signal finance/markets accounts to also pull from (optional).
DEFAULT_ACCOUNTS = [
    "DeItaone",       # Walter Bloomberg — fast headline relay
    "FirstSquawk",    # market headlines
    "unusual_whales", # flow / market chatter
]

# Crypto tickers → common names, so account-timeline filtering catches posts
# that say "Bitcoin" rather than "$BTC".
_CRYPTO_NAMES = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "DOGE": "dogecoin",
    "XRP": "ripple",
    "ADA": "cardano",
}

DC_NS = "{http://purl.org/dc/elements/1.1/}"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", text or "")).strip()


def _parse_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


def _env_list(name: str, default: List[str]) -> List[str]:
    raw = os.environ.get(name, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or default


class XScraper:
    """Scrapes recent X posts for a symbol via Nitter RSS search."""

    def __init__(
        self,
        instances: Optional[List[str]] = None,
        accounts: Optional[List[str]] = None,
        timeout: int = 10,
        max_age_hours: int = 24,
        backend: Optional[str] = None,
        cli_bin: Optional[str] = None,
    ) -> None:
        self.instances = [
            i.rstrip("/") for i in (instances or _env_list(
                "X_NITTER_INSTANCES", DEFAULT_NITTER_INSTANCES
            ))
        ]
        self.accounts = accounts or _env_list("X_ACCOUNTS", DEFAULT_ACCOUNTS)
        self.timeout = timeout
        self.max_age_hours = max_age_hours
        self.backend = (backend or os.environ.get("X_BACKEND", DEFAULT_BACKEND)).lower()
        self.cli_bin = cli_bin or os.environ.get("X_CLI_BIN", DEFAULT_CLI_BIN)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})

    # ── Public API ───────────────────────────────────────────

    def fetch_for_symbol(self, symbol: str, limit: int = 15) -> List[Dict[str, Any]]:
        """Return recent X posts mentioning the symbol's cashtag.

        Each post: {text, author, timestamp (ISO or None), url}.
        Returns [] on total failure (caller degrades to news-only).
        """
        clean = symbol.split("/")[0].upper()
        # Nitter handles a richer OR query; the CLIs are happier with a plain
        # cashtag, so keep the account-scoping to the Nitter backend.
        query = f"${clean}"
        if self.backend == "nitter" and self.accounts:
            from_clause = " OR ".join(f"from:{a}" for a in self.accounts)
            query = f"${clean} ({from_clause}) OR ${clean}"

        if self.backend == "cli":
            posts = self._search_cli(clean, limit)
        else:
            posts = self._search_nitter(query, limit)
        # Drop stale posts when timestamps are available.
        if posts and self.max_age_hours:
            cutoff = time.time() - self.max_age_hours * 3600
            kept = []
            for p in posts:
                ts = p.get("_epoch")
                if ts is None or ts >= cutoff:
                    kept.append(p)
            posts = kept or posts  # if all stale/undated, keep what we have
        return posts[:limit]

    # ── Internals ────────────────────────────────────────────

    def _search_nitter(self, query: str, limit: int) -> List[Dict[str, Any]]:
        for instance in self.instances:
            try:
                posts = self._search_instance(instance, query, limit)
                if posts:
                    logger.info("[X] %d posts from %s", len(posts), instance)
                    return posts
            except Exception as e:
                logger.debug("[X] instance %s failed: %s", instance, e)
                continue
        logger.info("[X] no posts (all Nitter instances failed or empty)")
        return []

    # ── CLI backend (agent-reach: twitter-cli / opencli) ──────

    def _cli_args(self, query: str, limit: int) -> List[str]:
        """Build the search argv for the configured CLI (no shell)."""
        bin_name = self.cli_bin
        if bin_name.endswith("opencli"):
            # opencli twitter search "<query>" -f json
            return [bin_name, "twitter", "search", query, "-f", "json"]
        # twitter-cli: twitter search "<query>" -n <limit> --json
        return [bin_name, "search", query, "-n", str(limit), "--json"]

    def _cli_args_userposts(self, account: str, limit: int) -> List[str]:
        """Build the user-posts argv (the stable twitter-cli path)."""
        bin_name = self.cli_bin
        if bin_name.endswith("opencli"):
            return [bin_name, "twitter", "user-posts", account, "-f", "json"]
        return [bin_name, "user-posts", account, "-n", str(limit), "--json"]

    def _run_cli(self, args: List[str]) -> Optional[str]:
        """Run a CLI command, returning stdout or None on any failure."""
        try:
            proc = subprocess.run(
                args, capture_output=True, text=True, timeout=max(self.timeout, 30)
            )
        except FileNotFoundError:
            logger.warning(
                "[X] cli backend: '%s' not found (install agent-reach / twitter-cli)",
                self.cli_bin,
            )
            return None
        except subprocess.TimeoutExpired:
            logger.warning("[X] cli backend timed out: %s", " ".join(args[:2]))
            return None
        if proc.returncode != 0:
            logger.debug("[X] cli exit %s: %s", proc.returncode, (proc.stderr or "")[:160])
            return None
        return proc.stdout

    @staticmethod
    def _symbol_needles(symbol: str) -> List[str]:
        """Strings whose presence marks a post as relevant to the symbol."""
        s = symbol.upper()
        needles = [f"${s}", f" {s} ", f"#{s}"]
        name = _CRYPTO_NAMES.get(s)
        if name:
            needles.append(name)
        return needles

    def _search_cli(self, symbol: str, limit: int) -> List[Dict[str, Any]]:
        # 1) Cashtag search — best when it works, but twitter-cli's search
        #    endpoint frequently 404s, so we fall back below.
        out = self._run_cli(self._cli_args(f"${symbol}", limit))
        posts = self._parse_cli_json(out or "", limit)
        if posts:
            logger.info("[X] %d posts via cli search for %s", len(posts), symbol)
            return posts

        # 2) Stable fallback: pull recent posts from configured finance accounts
        #    and keep the ones mentioning this symbol.
        needles = [n.lower() for n in self._symbol_needles(symbol)]
        matched: List[Dict[str, Any]] = []
        for account in self.accounts:
            out = self._run_cli(self._cli_args_userposts(account, 40))
            for p in self._parse_cli_json(out or "", 40):
                text = (p.get("text") or "").lower()
                if any(n in text for n in needles):
                    matched.append(p)
                    if len(matched) >= limit:
                        break
            if len(matched) >= limit:
                break
        logger.info(
            "[X] %d posts via cli user-posts fallback for %s", len(matched), symbol
        )
        return matched

    @staticmethod
    def _parse_cli_json(raw: str, limit: int) -> List[Dict[str, Any]]:
        """Tolerantly map CLI JSON to post dicts (schemas vary per backend)."""
        raw = (raw or "").strip()
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("[X] cli backend: non-JSON output")
            return []

        # Find the list of items regardless of envelope shape.
        items: List[Any] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("results", "tweets", "data", "items", "posts"):
                if isinstance(data.get(key), list):
                    items = data[key]
                    break
            else:
                if any(k in data for k in ("text", "full_text", "content")):
                    items = [data]

        def _first(d: Dict[str, Any], keys: List[str]) -> str:
            for k in keys:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return ""

        posts: List[Dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            text = _first(it, ["text", "full_text", "content", "tweet", "title"])
            if not text:
                continue
            # Author may be a plain string or a nested object (twitter-cli uses
            # author.screenName). _first only returns string values, so a dict
            # under "author" is skipped here and handled by the nested loop.
            author = _first(it, ["author", "username", "screen_name", "handle"])
            for nested_key in ("author", "user"):
                if not author and isinstance(it.get(nested_key), dict):
                    author = _first(
                        it[nested_key],
                        ["screenName", "screen_name", "username", "name", "handle"],
                    )
            if author and not author.startswith("@"):
                author = "@" + author
            ts = _first(it, ["createdAt", "created_at", "date", "time", "timestamp"])
            url = _first(it, ["url", "link", "permalink", "tweet_url"])
            epoch = None
            if ts:
                try:
                    epoch = datetime.fromisoformat(
                        ts.replace("Z", "+00:00")
                    ).timestamp()
                except ValueError:
                    dt = _parse_date(ts)
                    epoch = dt.timestamp() if dt else None
            posts.append(
                {
                    "text": _clean(text),
                    "author": author,
                    "timestamp": ts or None,
                    "_epoch": epoch,
                    "url": url,
                }
            )
            if len(posts) >= limit:
                break
        return posts

    def _search_instance(
        self, instance: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        r = self._session.get(
            f"{instance}/search/rss",
            params={"f": "tweets", "q": query},
            timeout=self.timeout,
        )
        if not r.ok:
            raise RuntimeError(f"status {r.status_code}")

        root = ET.fromstring(r.content)
        posts: List[Dict[str, Any]] = []
        for item in root.iter("item"):
            title = _clean(item.findtext("title", ""))
            if not title:
                continue
            author = (item.findtext(f"{DC_NS}creator") or "").strip()
            link = (item.findtext("link") or "").strip()
            dt = _parse_date(item.findtext("pubDate"))
            posts.append(
                {
                    "text": title,
                    "author": author,
                    "timestamp": dt.isoformat() if dt else None,
                    "_epoch": dt.timestamp() if dt else None,
                    "url": link,
                }
            )
            if len(posts) >= limit:
                break
        return posts
