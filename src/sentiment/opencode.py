"""OpenCode Go AI news sentiment analyzer.

Fetches recent news headlines for an asset and asks an OpenCode Go model
(OpenAI-compatible gateway) to return a sentiment score in [-1.0, +1.0]
plus a confidence in [0, 1] and a short reason.

The model is selectable via ``OPENCODE_MODEL`` (default ``mimo-v2.5``,
Xiaomi's MiMo V2.5) and reasoning depth via ``OPENCODE_REASONING_EFFORT``
(default ``high``). The gateway endpoint is overridable via
``OPENCODE_BASE_URL``. Authenticates with ``OPENCODE_API_KEY`` (Bearer token).

Falls back to a neutral score (0.0) if:
- OPENCODE_API_KEY is not set
- News fetch returns nothing
- The OpenCode API call fails
"""

import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

OPENCODE_ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
DEFAULT_MODEL = "mimo-v2.5"
DEFAULT_REASONING_EFFORT = "high"
# Relative weights when blending the model's per-source sub-scores. X posts are
# weighted heavier than news by default (more real-time signal); tune via env.
DEFAULT_X_WEIGHT = 2.0
DEFAULT_NEWS_WEIGHT = 1.0
NEWS_ENDPOINT = "https://query1.finance.yahoo.com/v1/finance/search"
CACHE_TTL_SECONDS = 4 * 60 * 60  # 4 hours
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}

# Strips an optional ```json ... ``` markdown fence around the model output.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class OpenCodeSentiment:
    """OpenCode Zen AI news sentiment analyzer with caching."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        reasoning_effort: Optional[str] = None,
        timeout: int = 30,
        enable_x: Optional[bool] = None,
    ) -> None:
        self._api_key = api_key if api_key is not None else os.environ.get(
            "OPENCODE_API_KEY", ""
        )
        self._model = model or os.environ.get("OPENCODE_MODEL", DEFAULT_MODEL)
        self._reasoning_effort = (
            reasoning_effort
            if reasoning_effort is not None
            else os.environ.get("OPENCODE_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
        )
        self._endpoint = os.environ.get("OPENCODE_BASE_URL", OPENCODE_ENDPOINT)
        self._timeout = timeout
        if enable_x is None:
            enable_x = os.environ.get("ENABLE_X_SENTIMENT", "true").lower() in (
                "true",
                "1",
                "yes",
                "on",
            )
        self._enable_x = enable_x
        self._x_weight = _env_float("X_SENTIMENT_WEIGHT", DEFAULT_X_WEIGHT)
        self._news_weight = _env_float("NEWS_SENTIMENT_WEIGHT", DEFAULT_NEWS_WEIGHT)
        self._x: Optional[Any] = None  # lazily constructed XScraper
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._cache: Dict[str, Dict[str, Any]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def model(self) -> str:
        return self._model

    # ── Public API ───────────────────────────────────────────

    def fetch_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Return sentiment for a symbol. Cached for 4h.

        Returns dict with:
          - sentimentScore: -1.0..+1.0
          - confidence: 0.0..1.0
          - reason: short string
          - model: model id used
          - cached: bool
        """
        clean = symbol.split("/")[0].upper()
        now = time.time()

        cached = self._cache.get(clean)
        if cached and (now - cached["timestamp"]) < CACHE_TTL_SECONDS:
            out = dict(cached["data"])
            out["cached"] = True
            return out

        default = {
            "sentimentScore": 0.0,
            "confidence": 0.0,
            "reason": "Sentiment analysis unconfigured or unavailable",
            "model": self._model,
        }

        if not self.is_configured:
            logger.debug("[OpenCode] OPENCODE_API_KEY not set; returning neutral")
            return default

        news = self._fetch_news(clean)
        posts = self._fetch_x(clean)
        if not news and not posts:
            return {
                **default,
                "reason": "No recent news or social posts found for this asset",
            }

        result = self._call_opencode(clean, news, posts)
        if result is None:
            return default

        # Cache
        self._cache[clean] = {"timestamp": now, "data": result}
        out = dict(result)
        out["cached"] = False
        return out

    # ── Internals ────────────────────────────────────────────

    def _fetch_news(self, symbol: str) -> List[Dict[str, Any]]:
        """Pull recent news for a symbol from Yahoo Finance search."""
        try:
            r = self._session.get(
                NEWS_ENDPOINT,
                params={"q": symbol, "newsCount": 10},
                timeout=self._timeout,
            )
            if not r.ok:
                logger.warning(f"[OpenCode] news fetch {symbol} status {r.status_code}")
                return []
            data = r.json()
            return data.get("news", []) or []
        except Exception as e:
            logger.error(f"[OpenCode] news fetch {symbol} error: {e}")
            return []

    def _fetch_x(self, symbol: str) -> List[Dict[str, Any]]:
        """Pull recent X (Twitter) posts for a symbol via the scraper."""
        if not self._enable_x:
            return []
        try:
            if self._x is None:
                from src.sentiment.x_source import XScraper

                self._x = XScraper()
            return self._x.fetch_for_symbol(symbol)
        except Exception as e:
            logger.warning("[OpenCode] X fetch %s error: %s", symbol, e)
            return []

    def _format_headlines(self, news_items: List[Dict[str, Any]]) -> str:
        lines = []
        for idx, item in enumerate(news_items):
            ts = item.get("providerPublishTime")
            date_str = (
                time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else "recent"
            )
            title = item.get("title", "").strip()
            publisher = item.get("publisher", "")
            lines.append(f'{idx + 1}. [{date_str}] "{title}" ({publisher})')
        return "\n".join(lines)

    def _format_posts(self, posts: List[Dict[str, Any]]) -> str:
        lines = []
        for idx, p in enumerate(posts):
            ts = p.get("timestamp") or "recent"
            date_str = ts[:10] if isinstance(ts, str) else "recent"
            author = p.get("author", "") or "@unknown"
            text = (p.get("text", "") or "").strip()
            lines.append(f'{idx + 1}. [{date_str}] {author}: "{text}"')
        return "\n".join(lines)

    def _call_opencode(
        self,
        symbol: str,
        news_items: List[Dict[str, Any]],
        posts: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict[str, Any]]:
        """POST headlines + social posts to OpenCode, parse the JSON response."""
        posts = posts or []
        sections = []
        if news_items:
            sections.append(
                "Recent news headlines:\n" + self._format_headlines(news_items)
            )
        if posts:
            sections.append(
                "Recent posts from X (Twitter):\n" + self._format_posts(posts)
            )
        evidence = "\n\n".join(sections)

        prompt = (
            f"You are a professional financial analyst AI.\n"
            f"Analyze the following recent news headlines and social media posts "
            f"for the asset symbol \"{symbol}\" to evaluate market sentiment.\n"
            f"Score the two sources SEPARATELY so they can be weighted downstream. "
            f"Discount hype, spam, or promotional posts.\n"
            f"Determine, each from -1.0 (extremely bearish) to +1.0 (extremely "
            f"bullish), with 0.0 for neutral/mixed:\n"
            f"1. newsScore — sentiment from the news headlines only "
            f"(use 0.0 if no headlines are provided).\n"
            f"2. xScore — sentiment from the X (Twitter) posts only "
            f"(use 0.0 if no posts are provided).\n"
            f"3. confidence — overall confidence from 0.0 to 1.0.\n"
            f"4. reason — a brief summary explanation.\n\n"
            f"{evidence}\n\n"
            f"You must return your output strictly in JSON format. Do not wrap in "
            f"markdown code blocks. The JSON must follow this structure:\n"
            f'{{"newsScore": <float>, "xScore": <float>, "confidence": <float>, "reason": "<string>"}}'
        )

        body: Dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        # MiMo V2.5 (and other reasoning models) accept OpenAI-style reasoning effort.
        if self._reasoning_effort and self._reasoning_effort.lower() != "none":
            body["reasoning_effort"] = self._reasoning_effort

        try:
            r = self._session.post(
                self._endpoint,
                json=body,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
            if not r.ok:
                logger.error(f"[OpenCode] API {r.status_code}: {r.text[:200]}")
                return None
            data = r.json()
            text = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            ) or ""
            text = _FENCE_RE.sub("", text.strip()).strip()
            if not text:
                return None
            parsed = json.loads(text)

            # Blend per-source sub-scores, weighting X posts more heavily.
            # Only sources that actually contributed evidence are included.
            def _opt_float(key: str) -> Optional[float]:
                if parsed.get(key) is None:
                    return None
                try:
                    return _clamp(float(parsed[key]), -1.0, 1.0)
                except (TypeError, ValueError):
                    return None

            news_score = _opt_float("newsScore")
            x_score = _opt_float("xScore")

            parts = []
            if news_items and news_score is not None:
                parts.append((self._news_weight, news_score))
            if posts and x_score is not None:
                parts.append((self._x_weight, x_score))

            total_w = sum(w for w, _ in parts)
            if total_w > 0:
                score = sum(w * s for w, s in parts) / total_w
            else:
                # Fallback: legacy single score if the model ignored sub-scores.
                score = _clamp(float(parsed.get("sentimentScore", 0)), -1.0, 1.0)

            return {
                "sentimentScore": _clamp(score, -1.0, 1.0),
                "confidence": _clamp(float(parsed.get("confidence", 0)), 0.0, 1.0),
                "reason": str(parsed.get("reason", "")).strip()[:280],
                "model": self._model,
                "sources": {"news": len(news_items), "x_posts": len(posts)},
                "subScores": {"news": news_score, "x": x_score},
                "weights": {"news": self._news_weight, "x": self._x_weight},
            }
        except Exception as e:
            logger.error(f"[OpenCode] call failed: {e}")
            return None
