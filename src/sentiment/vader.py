"""VADER sentiment analyzer — fast lexicon-based fallback."""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class VaderSentiment:
    """Wraps vaderSentiment.SentimentIntensityAnalyzer with a lazy import."""

    def __init__(self) -> None:
        self._analyzer = None
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

            self._analyzer = SentimentIntensityAnalyzer()
        except ImportError:
            logger.warning("[VADER] vaderSentiment not installed; returning neutral")

    def score(self, text: str) -> Dict[str, float]:
        """Return compound/neg/neu/pos scores in [-1, 1]."""
        if self._analyzer is None or not text:
            return {"neg": 0.0, "neu": 1.0, "pos": 0.0, "compound": 0.0}
        try:
            return self._analyzer.polarity_scores(text)
        except Exception as e:
            logger.error(f"[VADER] error: {e}")
            return {"neg": 0.0, "neu": 1.0, "pos": 0.0, "compound": 0.0}

    def score_batch(self, texts: List[str]) -> List[Dict[str, float]]:
        return [self.score(t) for t in texts]
