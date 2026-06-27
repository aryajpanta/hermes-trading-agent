"""Sentiment analysis module — multi-source: FinBERT + VADER + OpenCode AI."""

from src.sentiment.finbert import FinBertSentiment
from src.sentiment.opencode import OpenCodeSentiment
from src.sentiment.vader import VaderSentiment

__all__ = ["FinBertSentiment", "OpenCodeSentiment", "VaderSentiment"]
