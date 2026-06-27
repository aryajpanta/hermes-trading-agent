"""AI News + X Sentiment — turns sentiment into a strategy vote.

Wraps ``OpenCodeSentiment`` (MiMo V2.5 over Yahoo news + X/Twitter posts) and
emits its sentiment score as a directional signal so it participates in the
decision engine's weighted aggregation alongside the technical strategies.

Behaviour:
- direction  = sentimentScore  (already in [-1, +1])
- confidence = sentiment confidence (already in [0, 1])
- If sentiment is unconfigured / unavailable / errors, it returns a neutral
  zero-confidence signal, which the engine drops (so it simply doesn't vote).

Disable without removing the file via ``ENABLE_SENTIMENT_STRATEGY=false``.
"""

import logging
import os
from typing import Any, List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_ID = "sentiment_signal"


def _enabled() -> bool:
    return os.environ.get("ENABLE_SENTIMENT_STRATEGY", "true").lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


class SentimentSignalStrategy(BaseStrategy):
    """Emits a directional vote from AI news + X sentiment for the symbol."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="AI News + X Sentiment",
                source="OpenCode MiMo V2.5 (news + X/Twitter)",
                description=(
                    "Directional vote from AI-scored news headlines and X posts."
                ),
                category="sentiment",
                timeframes=["1d", "4h", "1h"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "Aggregate sentiment score is clearly bullish/bearish",
                    "with sufficient model confidence",
                ],
                exit_rules=["Sentiment flips against the position"],
                stop_loss_pct=0.04,
                take_profit_pct=0.08,
                position_size_pct=0.05,
                max_holding_period=7,
                min_confidence=0.3,
            )
        super().__init__(config)
        self._analyzer: Optional[Any] = None  # lazily constructed OpenCodeSentiment

    def required_indicators(self) -> List[str]:
        return []  # sentiment needs no technical indicators

    def minimum_data_points(self) -> int:
        return 1  # we only use the symbol, not the price history

    def _get_analyzer(self) -> Any:
        if self._analyzer is None:
            from src.sentiment.opencode import OpenCodeSentiment

            # One instance per strategy so its 4h cache persists across calls.
            self._analyzer = OpenCodeSentiment()
        return self._analyzer

    def evaluate(self, data: pd.DataFrame) -> Signal:
        if not _enabled():
            return self._make_signal(0.0, 0.0, "Sentiment strategy disabled.")

        symbol = ""
        try:
            symbol = str(data.attrs.get("symbol", "")).strip()
        except Exception:
            symbol = ""
        if not symbol:
            return self._make_signal(0.0, 0.0, "No symbol provided for sentiment.")

        try:
            result = self._get_analyzer().fetch_sentiment(symbol)
        except Exception as e:
            logger.warning("[sentiment_signal] %s failed: %s", symbol, e)
            return self._make_signal(0.0, 0.0, f"Sentiment fetch failed: {e}")

        score = float(result.get("sentimentScore", 0.0))
        confidence = float(result.get("confidence", 0.0))
        # Clamp defensively (Signal validation requires the ranges).
        score = max(-1.0, min(1.0, score))
        confidence = max(0.0, min(1.0, confidence))

        reason = str(result.get("reason", "")).strip()
        sources = result.get("sources", {})
        bias = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
        reasoning = (
            f"Sentiment {bias} ({score:+.2f}, conf {confidence:.2f}) "
            f"from {sources.get('news', 0)} news / {sources.get('x_posts', 0)} X posts. "
            f"{reason}"
        ).strip()

        return self._make_signal(
            direction=score,
            confidence=confidence,
            reasoning=reasoning[:280],
            symbol=symbol,
            metadata={
                "sentimentScore": score,
                "model": result.get("model"),
                "sources": sources,
                "cached": result.get("cached"),
            },
        )


register_strategy_class(STRATEGY_ID, SentimentSignalStrategy)
