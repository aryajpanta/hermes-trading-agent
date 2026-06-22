"""Ichimoku Cloud — Comprehensive trend system by Goichi Hosoda.

Uses 5 lines (Tenkan, Kijun, Senkou A/B, Chikou) to identify trend direction,
support/resistance, and momentum.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "ichimoku_cloud"


class IchimokuCloudStrategy(BaseStrategy):
    """Ichimoku Cloud strategy — comprehensive trend analysis system."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Ichimoku Cloud",
                source="Goichi Hosoda",
                description="Multi-line trend system: price above cloud is bullish, below is bearish.",
                category="trend",
                timeframes=["1d", "4h", "1w"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "Price above Kumo cloud (Senkou A and B)",
                    "Tenkan-sen crosses above Kijun-sen (TK cross)",
                    "Chikou span above price from 26 periods ago",
                    "Cloud is green (Senkou A > Senkou B)",
                ],
                exit_rules=[
                    "Price closes below Kumo cloud",
                    "Tenkan-sen crosses below Kijun-sen",
                    "Chikou span crosses below price",
                    "Cloud changes color (bearish turn)",
                ],
                stop_loss_pct=0.04,
                take_profit_pct=0.12,
                position_size_pct=0.05,
                max_holding_period=0,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["Ichimoku_Tenkan", "Ichimoku_Kijun", "Ichimoku_SenkouA", "Ichimoku_SenkouB", "Ichimoku_Chikou"]

    def minimum_data_points(self) -> int:
        return 52

    def evaluate(self, data: pd.DataFrame) -> Signal:
        high = data["high"]
        low = data["low"]
        close = data["close"]

        # Tenkan-sen (Conversion Line): 9-period midpoint
        tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2

        # Kijun-sen (Base Line): 26-period midpoint
        kijun = (high.rolling(26).max() + low.rolling(26).min()) / 2

        # Senkou Span A: (Tenkan + Kijun) / 2, shifted 26 periods ahead
        senkou_a = ((tenkan + kijun) / 2).shift(26)

        # Senkou Span B: 52-period midpoint, shifted 26 periods ahead
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)

        # Chikou Span: close shifted 26 periods back
        chikou = close.shift(-26)

        current_price = close.iloc[-1]
        current_tenkan = tenkan.iloc[-1]
        current_kijun = kijun.iloc[-1]
        current_senkou_a = senkou_a.iloc[-1]
        current_senkou_b = senkou_b.iloc[-1]

        prev_tenkan = tenkan.iloc[-2]
        prev_kijun = kijun.iloc[-2]

        if pd.isna(current_senkou_a) or pd.isna(current_senkou_b):
            return self._make_signal(0.0, 0.0, "Ichimoku data not yet available.")

        # Cloud top and bottom
        cloud_top = max(current_senkou_a, current_senkou_b)
        cloud_bottom = min(current_senkou_a, current_senkou_b)
        cloud_green = current_senkou_a > current_senkou_b

        # TK Cross
        tk_bullish_cross = prev_tenkan <= prev_kijun and current_tenkan > current_kijun
        tk_bearish_cross = prev_tenkan >= prev_kijun and current_tenkan < current_kijun

        score = 0
        reasons = []

        # Price above/below cloud
        if current_price > cloud_top:
            score += 2
            reasons.append("Price above Kumo cloud")
        elif current_price < cloud_bottom:
            score -= 2
            reasons.append("Price below Kumo cloud")

        # TK cross
        if tk_bullish_cross:
            score += 1
            reasons.append("Bullish TK cross")
        if tk_bearish_cross:
            score -= 1
            reasons.append("Bearish TK cross")

        # Cloud color
        if cloud_green:
            score += 1
            reasons.append("Green cloud (bullish)")
        else:
            score -= 1
            reasons.append("Red cloud (bearish)")

        if score >= 3:
            confidence = min(0.85, 0.6 + (score - 3) * 0.05)
            return self._make_signal(1.0, confidence, f"Ichimoku bullish ({score}): {', '.join(reasons)}.", metadata={"tenkan": current_tenkan, "kijun": current_kijun, "cloud_top": cloud_top})
        if score <= -3:
            confidence = min(0.85, 0.6 + (abs(score) - 3) * 0.05)
            return self._make_signal(-1.0, confidence, f"Ichimoku bearish ({score}): {', '.join(reasons)}.", metadata={"tenkan": current_tenkan, "kijun": current_kijun, "cloud_bottom": cloud_bottom})

        return self._make_signal(0.0, 0.3, f"Ichimoku neutral (score: {score}): {', '.join(reasons) if reasons else 'Mixed signals'}.", metadata={"score": score})


register_strategy_class(STRATEGY_ID, IchimokuCloudStrategy)
