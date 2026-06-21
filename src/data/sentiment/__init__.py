"""Sentiment Collection System for Trading Intelligence.

Provides financial news and social media sentiment analysis from
multiple sources (RSS, Reddit) with FinBERT/VADER scoring.
"""

from src.data.sentiment.models import SentimentSignal, SentimentSource, SentimentAggregate
from src.data.sentiment.collector import SentimentCollector, SentimentStorage
from src.data.sentiment.scorer import score_sentiment

__all__ = [
    "SentimentSignal",
    "SentimentSource",
    "SentimentAggregate",
    "SentimentCollector",
    "SentimentStorage",
    "score_sentiment",
]
