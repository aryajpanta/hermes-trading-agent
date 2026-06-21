"""Sentiment scoring engine with FinBERT primary and VADER fallback.

Provides financial text sentiment analysis using ProsusAI/finbert as the
primary model, falling back to VADER when transformers/torch are unavailable.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy-loaded model instances
_finbert_model: Optional[Any] = None
_finbert_tokenizer: Optional[Any] = None
_finbert_available: Optional[bool] = None


def _check_finbert_available() -> bool:
    """Check if FinBERT dependencies are available."""
    global _finbert_available
    if _finbert_available is not None:
        return _finbert_available
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        _finbert_available = True
    except ImportError:
        _finbert_available = False
        logger.info(
            "transformers/torch not installed; falling back to VADER for sentiment"
        )
    return _finbert_available


def _load_finbert() -> Tuple[Any, Any]:
    """Lazily load FinBERT model and tokenizer."""
    global _finbert_model, _finbert_tokenizer
    if _finbert_model is not None and _finbert_tokenizer is not None:
        return _finbert_model, _finbert_tokenizer

    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_name = "ProsusAI/finbert"
    logger.info("Loading FinBERT model: %s", model_name)
    _finbert_tokenizer = AutoTokenizer.from_pretrained(model_name)
    _finbert_model = AutoModelForSequenceClassification.from_pretrained(model_name)
    logger.info("FinBERT model loaded successfully")
    return _finbert_model, _finbert_tokenizer  # type: ignore[return-value]


def score_with_finbert(text: str) -> Tuple[float, float]:
    """Score text sentiment using FinBERT.

    Args:
        text: Text to analyze (truncated to 512 tokens).

    Returns:
        Tuple of (sentiment_score, confidence).
        Score ranges from -1.0 (bearish) to +1.0 (bullish).
        Confidence ranges from 0.0 to 1.0.
    """
    import torch

    model, tokenizer = _load_finbert()

    # Truncate to 512 tokens max
    inputs = tokenizer(
        text, return_tensors="pt", truncation=True, max_length=512, padding=True
    )

    with torch.no_grad():
        outputs = model(**inputs)
        probabilities = torch.nn.functional.softmax(outputs.logits, dim=-1)

    # FinBERT labels: positive, negative, neutral (in that order)
    probs = probabilities[0].tolist()
    pos_prob = probs[0]
    neg_prob = probs[1]
    neu_prob = probs[2]

    # Compute score: positive - negative, weighted by confidence
    score = pos_prob - neg_prob
    confidence = max(pos_prob, neg_prob, neu_prob)

    return float(score), float(confidence)


def score_with_vader(text: str) -> Tuple[float, float]:
    """Score text sentiment using VADER.

    Args:
        text: Text to analyze.

    Returns:
        Tuple of (sentiment_score, confidence).
        Score ranges from -1.0 (bearish) to +1.0 (bullish).
        Confidence ranges from 0.0 to 1.0.
    """
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    vs = analyzer.polarity_scores(text)

    # VADER compound ranges from -1 to 1
    score = vs["compound"]

    # Confidence based on how far from neutral (0.0)
    confidence = abs(score)

    return float(score), float(confidence)


def score_sentiment(text: str, model: str = "auto") -> Tuple[float, float]:
    """Score sentiment with automatic model selection.

    Uses FinBERT when available, falls back to VADER.

    Args:
        text: Text to analyze.
        model: Model preference - "finbert", "vader", or "auto" (default).

    Returns:
        Tuple of (sentiment_score, confidence).
        Score ranges from -1.0 (bearish) to +1.0 (bullish).
        Confidence ranges from 0.0 to 1.0.

    Raises:
        ValueError: If text is empty.
        RuntimeError: If the requested model is unavailable.
    """
    if not text or not text.strip():
        raise ValueError("Cannot score empty text")

    text = text.strip()

    if model == "vader":
        return score_with_vader(text)

    if model == "finbert":
        if not _check_finbert_available():
            raise RuntimeError(
                "FinBERT requested but transformers/torch not installed"
            )
        return score_with_finbert(text)

    # auto mode: try FinBERT first, fall back to VADER
    if _check_finbert_available():
        try:
            return score_with_finbert(text)
        except Exception as e:
            logger.warning("FinBERT scoring failed, falling back to VADER: %s", e)

    return score_with_vader(text)


def batch_score_sentiment(
    texts: List[str], model: str = "auto"
) -> List[Tuple[float, float]]:
    """Score sentiment for multiple texts.

    Args:
        texts: List of texts to analyze.
        model: Model preference.

    Returns:
        List of (sentiment_score, confidence) tuples.
    """
    return [score_sentiment(text, model=model) for text in texts]


def get_available_models() -> Dict[str, bool]:
    """Check which sentiment models are available.

    Returns:
        Dictionary mapping model names to availability status.
    """
    models: Dict[str, bool] = {"vader": True}
    models["finbert"] = _check_finbert_available()
    return models
