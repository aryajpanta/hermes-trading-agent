"""O'Neil CANSLIM — Growth momentum strategy by William O'Neil.

Combines fundamental (earnings growth, margins) with technical (price/volume)
analysis for high-growth stock selection.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "oneil_canslim"


class ONeilCANSLIM(BaseStrategy):
    """William O'Neil's CANSLIM growth momentum strategy."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="O'Neil CANSLIM",
                source="William O'Neil",
                description="Growth momentum: buy leading stocks with strong earnings, relative strength, and institutional sponsorship.",
                category="growth",
                timeframes=["1d", "1w"],
                assets=["stocks"],
                entry_rules=[
                    "Current quarterly EPS up 25%+ YoY (C: Current Earnings)",
                    "Annual EPS growth 25%+ over 3-5 years (A: Annual Growth)",
                    "New product/service/mgmt driving growth (N: New)",
                    "Supply/demand: heavy volume on up days (S: Supply/Demand)",
                    "Leader in group, RS rank top 20% (L: Leader/Ideology)",
                    "Institutional ownership increasing (I: Institutional Sponsorship)",
                    "Market in confirmed uptrend (M: Market Direction)",
                ],
                exit_rules=[
                    "Sell on 7-8% loss from purchase price",
                    "Sell if stock drops below 50-day MA on heavy volume",
                    "Sell after 20-25% gain or if gain stalls",
                    "Sell if earnings growth decelerates",
                ],
                stop_loss_pct=0.08,
                take_profit_pct=0.25,
                position_size_pct=0.05,
                max_holding_period=90,
                min_confidence=0.65,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["SMA_50", "SMA_200", "Volume_SMA", "RelativeStrength"]

    def minimum_data_points(self) -> int:
        return 200

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        volume = data["volume"]

        sma_50 = close.rolling(50).mean()
        sma_200 = close.rolling(200).mean()

        current_price = close.iloc[-1]
        current_sma50 = sma_50.iloc[-1]
        current_sma200 = sma_200.iloc[-1]

        # Volume analysis (Supply/Demand proxy)
        vol_sma_50 = volume.rolling(50).mean().iloc[-1]
        current_vol = volume.iloc[-1]
        vol_ratio = current_vol / vol_sma_50 if vol_sma_50 > 0 else 1.0

        # Price momentum (proxy for relative strength)
        price_change_6m = (current_price / close.iloc[-126] - 1) * 100 if len(close) > 126 else 0

        score: float = 0
        reasons = []

        # Technical proxies for CANSLIM criteria
        if current_price > current_sma50:
            score += 1
            reasons.append("Price above 50d MA")
        if current_sma50 > current_sma200:
            score += 1
            reasons.append("50d > 200d MA (uptrend)")
        if price_change_6m > 30:
            score += 1
            reasons.append(f"Strong 6m momentum (+{price_change_6m:.0f}%)")
        elif price_change_6m > 15:
            score += 0.5
            reasons.append(f"Moderate 6m momentum (+{price_change_6m:.0f}%)")
        if vol_ratio > 1.5 and current_price > close.iloc[-2]:
            score += 1
            reasons.append(f"Volume surge ({vol_ratio:.1f}x) on up day")
        if current_price > sma_200.iloc[-1] * 1.25:
            score += 1
            reasons.append("Price well above 200d MA")

        if score >= 4:
            confidence = min(0.85, 0.6 + (score - 4) * 0.1)
            return self._make_signal(1.0, confidence, f"CANSLIM bullish ({score:.1f}/5): {', '.join(reasons)}.", metadata={"score": score, "price_momentum_6m": price_change_6m})
        if score >= 2:
            return self._make_signal(0.4, 0.5, f"Partial CANSLIM ({score:.1f}/5): {', '.join(reasons)}.", metadata={"score": score})

        return self._make_signal(0.0, 0.3, f"CANSLIM criteria not met ({score:.1f}/5).", metadata={"score": score})


register_strategy_class(STRATEGY_ID, ONeilCANSLIM)
