"""FinBERT sentiment analyzer — uses HuggingFace transformers."""

import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MODEL_NAME = "ProsusAI/finbert"


class FinBertSentiment:
    """FinBERT model wrapper. Lazy-loads the model on first use."""

    def __init__(
        self, model_name: str = _MODEL_NAME, device: str = "cpu", max_length: int = 512
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self._tokenizer = None
        self._model = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
            import torch

            logger.info(f"[FinBERT] loading {self.model_name} on {self.device}")
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name
            )
            self._model.to(self.device)
            self._model.eval()
            self._torch = torch
            self._loaded = True
            logger.info("[FinBERT] loaded")
        except Exception as e:
            logger.error(f"[FinBERT] load failed: {e}")
            self._loaded = False

    def score(self, text: str) -> Dict[str, float]:
        """Return pos/neg/neu scores summing to 1.0."""
        if not text:
            return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}
        self._load()
        if not self._loaded:
            return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

        try:
            import torch

            inputs = self._tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=self.max_length,
                padding=True,
            )
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._model(**inputs)
            probs = outputs.logits.softmax(dim=-1).cpu().tolist()[0]
            # FinBERT label order: positive, negative, neutral
            return {
                "positive": float(probs[0]),
                "negative": float(probs[1]),
                "neutral": float(probs[2]),
            }
        except Exception as e:
            logger.error(f"[FinBERT] inference error: {e}")
            return {"positive": 0.0, "negative": 0.0, "neutral": 1.0}

    def score_batch(self, texts: List[str]) -> List[Dict[str, float]]:
        return [self.score(t) for t in texts]
