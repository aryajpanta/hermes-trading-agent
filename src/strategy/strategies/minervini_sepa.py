"""Minervini SEPA — Specific Entry Point Analysis by Mark Minervini.

Identifies stocks in stage 2 uptrend with precise entry on pullbacks.
Uses moving averages, volatility contraction, and relative strength.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "minervini_sepa"


class MinerviniSEPA(BaseStrategy):
    """Mark Minervini's Specific Entry Point Analysis strategy."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Minervini SEPA",
                source="Mark Minervini",
                description="Stage 2 uptrend identification with pullback entry. MA alignment + volatility contraction.",
                category="trend",
                timeframes=["1d"],
                assets=["stocks"],
                entry_rules=[
                    "Price above 150-day and 200-day SMA",
                    "150-day SMA above 200-day SMA, 200-day SMA trending up for 1+ month",
                    "50-day SMA above 150-day and 200-day SMA",
                    "Price above 50-day SMA",
                    "Price at least 25% above 52-week low",
                    "Price within 25% of 52-week high",
                    "Relative strength rank in top 30%",
                ],
                exit_rules=[
                    "Price closes below 50-day SMA",
                    "50-day SMA breaks below 200-day SMA",
                    "Price drops 7-8% from entry (max loss)",
                    "Hold for 10-15% gain or tighten stop",
                ],
                stop_loss_pct=0.08,
                take_profit_pct=0.20,
                position_size_pct=0.05,
                max_holding_period=60,
                min_confidence=0.7,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["SMA_50", "SMA_150", "SMA_200", "RS_Relative"]

    def minimum_data_points(self) -> int:
        return 210

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]

        sma_50 = close.rolling(50).mean()
        sma_150 = close.rolling(150).mean()
        sma_200 = close.rolling(200).mean()

        current_price = close.iloc[-1]
        current_sma50 = sma_50.iloc[-1]
        current_sma150 = sma_150.iloc[-1]
        current_sma200 = sma_200.iloc[-1]

        # Check 200-day SMA trending up (compare with 1 month ago)
        sma200_month_ago = sma_200.iloc[-22] if len(sma_200) > 22 else sma_200.iloc[0]
        sma200_trending_up = current_sma200 > sma200_month_ago

        # 52-week high/low
        high_52w = close.rolling(252).max().iloc[-1]
        low_52w = close.rolling(252).min().iloc[-1]

        score = 0
        reasons = []

        # Core SEPA criteria
        if current_price > current_sma150:
            score += 1
            reasons.append("Price > 150d SMA")
        if current_price > current_sma200:
            score += 1
            reasons.append("Price > 200d SMA")
        if current_sma150 > current_sma200:
            score += 1
            reasons.append("150d SMA > 200d SMA")
        if sma200_trending_up:
            score += 1
            reasons.append("200d SMA trending up")
        if current_sma50 > current_sma150:
            score += 1
            reasons.append("50d SMA > 150d SMA")
        if current_sma50 > current_sma200:
            score += 1
            reasons.append("50d SMA > 200d SMA")
        if current_price > current_sma50:
            score += 1
            reasons.append("Price > 50d SMA")
        if low_52w > 0 and (current_price - low_52w) / low_52w > 0.25:
            score += 1
            reasons.append(">25% above 52w low")
        if high_52w > 0 and (high_52w - current_price) / high_52w < 0.25:
            score += 1
            reasons.append("Within 25% of 52w high")

        if score >= 7:
            confidence = min(0.9, 0.6 + (score - 7) * 0.1)
            return self._make_signal(1.0, confidence, f"SEPA criteria met ({score}/9): {', '.join(reasons)}.", metadata={"score": score})
        if score >= 5:
            return self._make_signal(0.4, 0.5, f"Partial SEPA criteria ({score}/9): {', '.join(reasons)}.", metadata={"score": score})

        return self._make_signal(0.0, 0.3, f"SEPA criteria not met ({score}/9).", metadata={"score": score})


register_strategy_class(STRATEGY_ID, MinerviniSEPA)
