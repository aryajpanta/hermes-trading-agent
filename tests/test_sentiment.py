"""Sentiment analyzer tests.

Run: pytest tests/test_sentiment.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sentiment.opencode import OpenCodeSentiment
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


class TestOpenCodeSentiment:
    def test_unconfigured_returns_neutral(self):
        # Don't set the key
        os.environ.pop("OPENCODE_API_KEY", None)
        analyzer = OpenCodeSentiment(api_key="")
        result = analyzer.fetch_sentiment("BTC")
        assert result["sentimentScore"] == 0.0
        assert result["confidence"] == 0.0
        assert "unconfigured" in result["reason"].lower() or "neutral" in result["reason"].lower()

    def test_default_model_and_effort(self):
        os.environ.pop("OPENCODE_MODEL", None)
        os.environ.pop("OPENCODE_REASONING_EFFORT", None)
        analyzer = OpenCodeSentiment(api_key="")
        assert analyzer.model == "mimo-v2.5"
        assert analyzer._reasoning_effort == "high"

    def test_clamp_bounds(self):
        # Inline-test the clamp helper
        from src.sentiment.opencode import _clamp

        assert _clamp(2.0, -1.0, 1.0) == 1.0
        assert _clamp(-2.0, -1.0, 1.0) == -1.0
        assert _clamp(0.5, -1.0, 1.0) == 0.5

    def test_no_news_and_no_posts_returns_neutral(self):
        analyzer = OpenCodeSentiment(api_key="k", enable_x=False)
        analyzer._fetch_news = lambda s: []
        result = analyzer.fetch_sentiment("BTC")
        assert result["sentimentScore"] == 0.0
        assert "no recent news" in result["reason"].lower()

    def test_x_posts_feed_into_prompt(self):
        """Posts are fetched and combined with news in the model prompt."""
        captured = {}

        class FakeResp:
            ok = True
            status_code = 200

            def json(self):
                return {
                    "choices": [
                        {"message": {"content": '{"sentimentScore":0.6,"confidence":0.7,"reason":"bullish chatter"}'}}
                    ]
                }

        analyzer = OpenCodeSentiment(api_key="k", enable_x=True)
        analyzer._fetch_news = lambda s: [
            {"title": "Asset rallies", "publisher": "Reuters", "providerPublishTime": 0}
        ]
        analyzer._fetch_x = lambda s: [
            {"text": "$BTC looking strong", "author": "@trader", "timestamp": "2026-06-27T00:00:00+00:00"}
        ]

        def fake_post(url, json=None, headers=None, timeout=None):
            captured["body"] = json
            return FakeResp()

        analyzer._session.post = fake_post
        result = analyzer.fetch_sentiment("BTC")

        prompt = captured["body"]["messages"][0]["content"]
        assert "Recent news headlines" in prompt
        assert "Recent posts from X" in prompt
        assert "looking strong" in prompt
        assert result["sources"] == {"news": 1, "x_posts": 1}
        assert result["sentimentScore"] == 0.6

    def test_enable_x_false_skips_scraper(self):
        analyzer = OpenCodeSentiment(api_key="k", enable_x=False)
        assert analyzer._fetch_x("BTC") == []

    def _mock_post(self, analyzer, payload_json):
        class FakeResp:
            ok = True
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": payload_json}}]}

        def fake_post(url, json=None, headers=None, timeout=None):
            return FakeResp()

        analyzer._session.post = fake_post

    def test_x_weighted_heavier_than_news(self):
        # X bullish (+1), news bearish (-1). Default weights x=2, news=1.
        # Blend = (1*-1 + 2*+1) / 3 = +0.333 — X dominates.
        analyzer = OpenCodeSentiment(api_key="k", enable_x=True)
        analyzer._fetch_news = lambda s: [{"title": "down", "publisher": "R", "providerPublishTime": 0}]
        analyzer._fetch_x = lambda s: [{"text": "up", "author": "@a", "timestamp": None}]
        self._mock_post(analyzer, '{"newsScore":-1.0,"xScore":1.0,"confidence":0.8,"reason":"x"}')

        res = analyzer.fetch_sentiment("BTC")
        assert abs(res["sentimentScore"] - (1 / 3)) < 0.01
        assert res["subScores"] == {"news": -1.0, "x": 1.0}
        assert res["weights"]["x"] == 2.0

    def test_custom_x_weight(self, monkeypatch):
        monkeypatch.setenv("X_SENTIMENT_WEIGHT", "4.0")
        analyzer = OpenCodeSentiment(api_key="k", enable_x=True)
        analyzer._fetch_news = lambda s: [{"title": "down", "publisher": "R", "providerPublishTime": 0}]
        analyzer._fetch_x = lambda s: [{"text": "up", "author": "@a", "timestamp": None}]
        self._mock_post(analyzer, '{"newsScore":-1.0,"xScore":1.0,"confidence":0.8,"reason":"x"}')
        # (1*-1 + 4*1)/5 = +0.6
        res = analyzer.fetch_sentiment("BTC")
        assert abs(res["sentimentScore"] - 0.6) < 0.01

    def test_no_x_posts_uses_news_only(self):
        # No posts -> X weight is irrelevant; only newsScore counts.
        analyzer = OpenCodeSentiment(api_key="k", enable_x=True)
        analyzer._fetch_news = lambda s: [{"title": "up", "publisher": "R", "providerPublishTime": 0}]
        analyzer._fetch_x = lambda s: []
        self._mock_post(analyzer, '{"newsScore":0.5,"xScore":0.9,"confidence":0.7,"reason":"x"}')
        res = analyzer.fetch_sentiment("BTC")
        assert res["sentimentScore"] == 0.5
        assert res["sources"]["x_posts"] == 0


class TestXScraper:
    def test_parses_nitter_rss(self):
        from src.sentiment.x_source import XScraper

        rss = b"""<?xml version="1.0"?>
        <rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>
          <item>
            <title>$NVDA breaking out hard today</title>
            <dc:creator>@chartguy</dc:creator>
            <link>https://nitter.net/chartguy/status/1</link>
            <pubDate>Sat, 27 Jun 2026 12:00:00 GMT</pubDate>
          </item>
          <item>
            <title>Bearish on $NVDA into earnings</title>
            <dc:creator>@bear</dc:creator>
            <link>https://nitter.net/bear/status/2</link>
            <pubDate>Sat, 27 Jun 2026 11:00:00 GMT</pubDate>
          </item>
        </channel></rss>"""

        class FakeResp:
            ok = True
            status_code = 200
            content = rss

        x = XScraper(instances=["https://fake.instance"], accounts=[], max_age_hours=0)
        x._session.get = lambda url, params=None, timeout=None: FakeResp()
        posts = x.fetch_for_symbol("NVDA")
        assert len(posts) == 2
        assert posts[0]["text"] == "$NVDA breaking out hard today"
        assert posts[0]["author"] == "@chartguy"
        assert posts[0]["url"].endswith("/status/1")

    def test_all_instances_fail_returns_empty(self):
        from src.sentiment.x_source import XScraper

        def boom(*a, **k):
            raise RuntimeError("network down")

        x = XScraper(instances=["https://a", "https://b"], accounts=[])
        x._session.get = boom
        assert x.fetch_for_symbol("BTC") == []

    def test_cli_args_twitter_vs_opencli(self):
        from src.sentiment.x_source import XScraper

        tw = XScraper(backend="cli", cli_bin="twitter")
        assert tw._cli_args("$NVDA", 10) == [
            "twitter", "search", "$NVDA", "-n", "10", "--json"
        ]
        oc = XScraper(backend="cli", cli_bin="opencli")
        assert oc._cli_args("$NVDA", 10) == [
            "opencli", "twitter", "search", "$NVDA", "-f", "json"
        ]

    def test_cli_json_tolerant_parsing(self):
        from src.sentiment.x_source import XScraper

        # Envelope with a "tweets" key; varied field names across items.
        raw = (
            '{"tweets": ['
            '{"full_text": "$NVDA ripping", "user": {"screen_name": "bull"}, '
            '"created_at": "2026-06-27T12:00:00Z", "url": "https://x.com/bull/1"},'
            '{"text": "$NVDA dump incoming", "author": "bear"}'
            ']}'
        )
        posts = XScraper._parse_cli_json(raw, limit=10)
        assert len(posts) == 2
        assert posts[0]["text"] == "$NVDA ripping"
        assert posts[0]["author"] == "@bull"  # nested user.screen_name, @-normalized
        assert posts[0]["_epoch"] is not None
        assert posts[1]["author"] == "@bear"

    def test_cli_parses_twitter_cli_userposts_schema(self):
        from src.sentiment.x_source import XScraper

        # Real twitter-cli user-posts shape: {data: [{text, author:{screenName}, createdAt}]}
        raw = (
            '{"ok": true, "data": ['
            '{"id": "1", "text": "Thoughts on $NVDA earnings", '
            '"author": {"screenName": "DeItaone", "name": "Walter"}, '
            '"createdAt": "2026-06-27T12:00:00Z"}]}'
        )
        posts = XScraper._parse_cli_json(raw, limit=10)
        assert len(posts) == 1
        assert posts[0]["author"] == "@DeItaone"
        assert "NVDA" in posts[0]["text"]

    def test_symbol_needles(self):
        from src.sentiment.x_source import XScraper

        x = XScraper(backend="cli")
        assert "$NVDA" in x._symbol_needles("NVDA")
        assert "bitcoin" in x._symbol_needles("BTC")

    def test_cli_backend_missing_binary_returns_empty(self):
        from src.sentiment.x_source import XScraper

        # Nonexistent binary -> FileNotFoundError handled -> []
        x = XScraper(backend="cli", cli_bin="definitely-not-a-real-binary-xyz")
        assert x.fetch_for_symbol("BTC") == []


class TestSentimentStrategy:
    """The sentiment-as-a-strategy-vote integration (#2)."""

    def _df(self):
        import pandas as pd

        df = pd.DataFrame(
            {"open": [1, 2], "high": [1, 2], "low": [1, 2], "close": [1, 2], "volume": [10, 20]}
        )
        df.attrs["symbol"] = "NVDA"
        return df

    def _strategy(self, fake_result=None, raises=False):
        from src.strategy.strategies.sentiment_signal import SentimentSignalStrategy

        s = SentimentSignalStrategy()

        class FakeAnalyzer:
            def fetch_sentiment(self, symbol):
                if raises:
                    raise RuntimeError("boom")
                return fake_result

        s._analyzer = FakeAnalyzer()
        return s

    def test_maps_sentiment_to_signal(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SENTIMENT_STRATEGY", "true")
        s = self._strategy(
            {
                "sentimentScore": 0.62,
                "confidence": 0.74,
                "reason": "bullish",
                "model": "mimo-v2.5",
                "sources": {"news": 8, "x_posts": 3},
                "cached": False,
            }
        )
        sig = s.evaluate(self._df())
        assert sig.direction == 0.62
        assert sig.confidence == 0.74
        assert sig.metadata["sources"] == {"news": 8, "x_posts": 3}

    def test_disabled_returns_neutral(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SENTIMENT_STRATEGY", "false")
        s = self._strategy({"sentimentScore": 0.9, "confidence": 0.9})
        sig = s.evaluate(self._df())
        assert sig.direction == 0.0 and sig.confidence == 0.0

    def test_no_symbol_returns_neutral(self, monkeypatch):
        import pandas as pd

        monkeypatch.setenv("ENABLE_SENTIMENT_STRATEGY", "true")
        s = self._strategy({"sentimentScore": 0.9, "confidence": 0.9})
        df = pd.DataFrame({"open": [1], "high": [1], "low": [1], "close": [1], "volume": [1]})
        sig = s.evaluate(df)  # no attrs["symbol"]
        assert sig.direction == 0.0 and sig.confidence == 0.0

    def test_analyzer_error_returns_neutral(self, monkeypatch):
        monkeypatch.setenv("ENABLE_SENTIMENT_STRATEGY", "true")
        s = self._strategy(raises=True)
        sig = s.evaluate(self._df())
        assert sig.direction == 0.0 and sig.confidence == 0.0

    def test_registered_and_discoverable(self):
        from src.strategy.library import _discover_strategies, list_strategies

        _discover_strategies()
        ids = [s.id for s in list_strategies()]
        assert "sentiment_signal" in ids
