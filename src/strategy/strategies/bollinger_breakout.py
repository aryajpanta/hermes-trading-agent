"""Bollinger Band Breakout — Volatility breakout strategy by John Bollinger.

Buy when price breaks above upper band with volume confirmation.
Sell when price breaks below lower band or mean-reverts from upper band.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "bollinger_breakout"


class BollingerBreakoutStrategy(BaseStrategy):
    """Bollinger Band Breakout strategy."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Bollinger Band Breakout",
                source="John Bollinger",
                description="Trade breakouts above/below Bollinger Bands with volume confirmation.",
                category="breakout",
                timeframes=["1d", "4h", "1h"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "Price closes above upper Bollinger Band (20, 2)",
                    "Volume is above 20-period average volume",
                    "Bandwidth is expanding (volatility increasing)",
                ],
                exit_rules=[
                    "Price closes below middle band (20-period SMA)",
                    "Price closes inside bands after breakout",
                    "Bandwidth starts contracting",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.08,
                position_size_pct=0.05,
                max_holding_period=15,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["BB_Upper", "BB_Middle", "BB_Lower", "BB_Width"]

    def minimum_data_points(self) -> int:
        return 25

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        volume = data["volume"]

        sma_20 = close.rolling(20).mean()
        std_20 = close.rolling(20).std()
        upper = sma_20 + 2 * std_20
        lower = sma_20 - 2 * std_20
        width = (upper - lower) / sma_20

        current_close = close.iloc[-1]
        current_upper = upper.iloc[-1]
        current_lower = lower.iloc[-1]
        current_middle = sma_20.iloc[-1]
        current_width = width.iloc[-1]
        prev_width = width.iloc[-2]

        avg_volume = volume.rolling(20).mean().iloc[-1]
        current_volume = volume.iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

        # Bullish breakout
        if current_close > current_upper:
            confidence = 0.65
            reasoning = f"Price ({current_close:.2f}) broke above upper band ({current_upper:.2f})."
            if volume_ratio > 1.5:
                confidence = min(0.9, confidence + 0.15)
                reasoning += f" Volume surge ({volume_ratio:.1f}x avg)."
            if current_width > prev_width:
                confidence = min(0.9, confidence + 0.1)
                reasoning += " Bandwidth expanding."
            return self._make_signal(direction=1.0, confidence=confidence, reasoning=reasoning, metadata={"bb_upper": current_upper, "volume_ratio": volume_ratio})

        # Bearish breakdown
        if current_close < current_lower:
            confidence = 0.65
            reasoning = f"Price ({current_close:.2f}) broke below lower band ({current_lower:.2f})."
            if volume_ratio > 1.5:
                confidence = min(0.9, confidence + 0.15)
                reasoning += f" Volume surge ({volume_ratio:.1f}x avg)."
            if current_width > prev_width:
                confidence = min(0.9, confidence + 0.1)
                reasoning += " Bandwidth expanding."
            return self._make_signal(direction=-1.0, confidence=confidence, reasoning=reasoning, metadata={"bb_lower": current_lower, "volume_ratio": volume_ratio})

        # Mean reversion from upper band
        prev_close = close.iloc[-2]
        prev_upper = upper.iloc[-2]
        if prev_close > prev_upper and current_close < current_upper:
            return self._make_signal(-0.6, 0.6, f"Price rejecting upper band. Falling from {prev_close:.2f} to {current_close:.2f}.")

        # Near lower band — potential reversal
        band_range = current_upper - current_lower
        band_position = (current_close - current_lower) / band_range if band_range > 0 else 0.5
        if band_position < 0.15:
            return self._make_signal(0.5, 0.5, f"Price near lower band ({band_position:.1%} of range). Potential bounce.")

        return self._make_signal(0.0, 0.3, f"Price within bands ({band_position:.1%} of range). No breakout signal.")


register_strategy_class(STRATEGY_ID, BollingerBreakoutStrategy)
