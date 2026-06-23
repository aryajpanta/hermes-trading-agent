"""Sentiment analyzer tests.

Run: pytest tests/test_sentiment.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sentiment.gemini import GeminiSentiment
from src.sentiment.vader import VaderSentiment


class TestVaderSentiment:
    def test_neutral(self):
        v = VaderSentiment()
        s = v.score("The market opened at 9:30 AM today.")
        assert s["compound"] == 0.0
        assert s["neu"] == 1.0

    def test_positive(self):
        v = VaderSentiment()
        s = v.score("Stock surges on incredible earnings beat! Great rally.")
        assert s["compound"] > 0.3
        assert s["pos"] > s["neg"]

    def test_negative(self):
        v = VaderSentiment()
        s = v.score("Market crashes on terrible losses. Awful crash and disaster.")
        assert s["compound"] < -0.3
        assert s["neg"] > s["pos"]

    def test_empty(self):
        v = VaderSentiment()
        s = v.score("")
        assert s == {"neg": 0.0, "neu": 1.0, "pos": 0.0, "compound": 0.0}

    def test_batch(self):
        v = VaderSentiment()
        scores = v.score_batch(["Good news", "Bad news", ""])
        assert len(scores) == 3
        assert scores[0]["compound"] > 0
        assert scores[1]["compound"] < 0


class TestGeminiSentiment:
    def test_unconfigured_returns_neutral(self):
        # Don't set the key
        os.environ.pop("GEMINI_API_KEY", None)
        g = GeminiSentiment(api_key="")
        result = g.fetch_sentiment("BTC")
        assert result["sentimentScore"] == 0.0
        assert result["confidence"] == 0.0
        assert "unconfigured" in result["reason"].lower() or "neutral" in result["reason"].lower()

    def test_clamp_bounds(self):
        g = GeminiSentiment(api_key="")
        # Inline-test the clamp helper
        from src.sentiment.gemini import _clamp

        assert _clamp(2.0, -1.0, 1.0) == 1.0
        assert _clamp(-2.0, -1.0, 1.0) == -1.0
        assert _clamp(0.5, -1.0, 1.0) == 0.5
