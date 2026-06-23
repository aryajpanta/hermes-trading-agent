"""Gemini AI news sentiment analyzer.

Ported from hermes-trading-agent (HTA) to Python. Fetches recent news
headlines for an asset and asks Gemini to return a sentiment score in
[-1.0, +1.0] plus a confidence in [0, 1] and a short reason.

Falls back to a neutral score (0.0) if:
- GEMINI_API_KEY is not set
- News fetch returns nothing
- The Gemini API call fails
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-1.5-flash:generateContent"
)
NEWS_ENDPOINT = "https://query1.finance.yahoo.com/v1/finance/search"
CACHE_TTL_SECONDS = 4 * 60 * 60  # 4 hours
DEFAULT_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class GeminiSentiment:
    """Gemini AI news sentiment analyzer with caching."""

    def __init__(self, api_key: Optional[str] = None, timeout: int = 20) -> None:
        self._api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update(DEFAULT_HEADERS)
        self._cache: Dict[str, Dict[str, Any]] = {}

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    # ── Public API ───────────────────────────────────────────

    def fetch_sentiment(self, symbol: str) -> Dict[str, Any]:
        """Return sentiment for a symbol. Cached for 4h.

        Returns dict with:
          - sentimentScore: -1.0..+1.0
          - confidence: 0.0..1.0
          - reason: short string
          - cached: bool
          - timestamp: ISO8601
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
        }

        if not self.is_configured:
            logger.debug("[Gemini] GEMINI_API_KEY not set; returning neutral")
            return default

        news = self._fetch_news(clean)
        if not news:
            return {
                **default,
                "reason": "No recent news articles found for this asset",
            }

        result = self._call_gemini(clean, news)
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
                logger.warning(f"[Gemini] news fetch {symbol} status {r.status_code}")
                return []
            data = r.json()
            return data.get("news", []) or []
        except Exception as e:
            logger.error(f"[Gemini] news fetch {symbol} error: {e}")
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

    def _call_gemini(
        self, symbol: str, news_items: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """POST headlines to Gemini, parse JSON response."""
        headlines = self._format_headlines(news_items)
        prompt = (
            f"You are a professional financial analyst AI.\n"
            f"Analyze the following recent news headlines for the asset symbol "
            f"\"{symbol}\" to evaluate market sentiment.\n"
            f"Determine:\n"
            f"1. A sentiment score from -1.0 (extremely bearish) to +1.0 "
            f"(extremely bullish). Neutral news or mixed sentiment should be near 0.0.\n"
            f"2. A confidence score from 0.0 (no confidence/insufficient news) to "
            f"1.0 (very high confidence).\n"
            f"3. A brief summary explanation of your reasoning.\n\n"
            f"Here are the news headlines:\n{headlines}\n\n"
            f"You must return your output strictly in JSON format. Do not wrap in "
            f"markdown code blocks. The JSON must follow this structure:\n"
            f'{{"sentimentScore": <float>, "confidence": <float>, "reason": "<string>"}}'
        )

        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json"},
        }

        try:
            r = self._session.post(
                f"{GEMINI_ENDPOINT}?key={self._api_key}",
                json=body,
                timeout=self._timeout,
            )
            if not r.ok:
                logger.error(
                    f"[Gemini] API {r.status_code}: {r.text[:200]}"
                )
                return None
            data = r.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
            )
            if not text:
                return None
            parsed = json.loads(text.strip())
            return {
                "sentimentScore": _clamp(float(parsed.get("sentimentScore", 0)), -1.0, 1.0),
                "confidence": _clamp(float(parsed.get("confidence", 0)), 0.0, 1.0),
                "reason": str(parsed.get("reason", "")).strip()[:280],
            }
        except Exception as e:
            logger.error(f"[Gemini] call failed: {e}")
            return None
