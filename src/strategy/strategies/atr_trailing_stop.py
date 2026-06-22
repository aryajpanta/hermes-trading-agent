"""ATR Trailing Stop — Trend-following with dynamic stop by Welles Wilder.

Uses Average True Range to set trailing stops that adapt to volatility.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "atr_trailing_stop"


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


class ATRTrailingStopStrategy(BaseStrategy):
    """ATR Trailing Stop strategy — volatility-adaptive trend following."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="ATR Trailing Stop",
                source="Wilder",
                description="Trend-following with ATR-based trailing stops for adaptive risk management.",
                category="trend",
                timeframes=["1d", "4h"],
                assets=["stocks", "crypto", "forex", "commodities"],
                entry_rules=[
                    "Price breaks above 20-day high",
                    "ATR(14) confirms volatility is expanding",
                    "Trailing stop set at entry price - 3 * ATR",
                ],
                exit_rules=[
                    "Price closes below 3x ATR trailing stop",
                    "ATR trailing stop ratchets up as price rises",
                    "Trend reversal: price breaks 10-day low",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.10,
                position_size_pct=0.03,
                max_holding_period=0,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["ATR_14", "HighestHigh_20"]

    def minimum_data_points(self) -> int:
        return 25

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        high = data["high"]
        low = data["low"]

        atr = _compute_atr(high, low, close, 14)
        highest_20 = high.rolling(20).max()

        current_price = close.iloc[-1]
        current_atr = atr.iloc[-1]
        current_hh20 = highest_20.iloc[-2]  # Previous bar's 20-day high
        prev_close = close.iloc[-2]

        # ATR expansion check
        atr_5_ago = atr.iloc[-5] if len(atr) > 5 else current_atr
        atr_expanding = current_atr > atr_5_ago * 1.1

        # Long entry: break above 20-day high with ATR expansion
        if prev_close <= current_hh20 and current_price > current_hh20:
            confidence = 0.65
            if atr_expanding:
                confidence = min(0.85, confidence + 0.15)
            return self._make_signal(
                direction=1.0,
                confidence=confidence,
                reasoning=f"20-day high breakout ({current_price:.2f} > {current_hh20:.2f}). ATR: {current_atr:.2f} ({'expanding' if atr_expanding else 'stable'}).",
                metadata={"atr": current_atr, "stop_level": current_price - 3 * current_atr},
            )

        # Check trailing stop: price below 3x ATR from recent high
        recent_high = high.iloc[-20:].max()
        trailing_stop = recent_high - 3 * current_atr

        if current_price < trailing_stop:
            return self._make_signal(
                direction=-1.0,
                confidence=0.8,
                reasoning=f"ATR trailing stop hit: price ({current_price:.2f}) below stop ({trailing_stop:.2f}). Recent high: {recent_high:.2f}.",
                metadata={"atr": current_atr, "stop_level": trailing_stop, "recent_high": recent_high},
            )

        # Near stop level
        if current_price < trailing_stop * 1.02:
            return self._make_signal(
                direction=-0.5,
                confidence=0.6,
                reasoning=f"Price ({current_price:.2f}) approaching ATR stop ({trailing_stop:.2f}). Tighten position.",
                metadata={"atr": current_atr, "stop_level": trailing_stop},
            )

        # Trend continuation
        if current_price > current_hh20 and current_atr > 0:
            profit_above_stop = (current_price - trailing_stop) / current_atr
            if profit_above_stop > 3:
                return self._make_signal(0.3, 0.4, f"Strong trend: {profit_above_stop:.1f} ATR above trailing stop. Consider taking partial profits.")

        return self._make_signal(0.0, 0.3, f"ATR trailing stop: {trailing_stop:.2f}. Price: {current_price:.2f}. No signal.")


register_strategy_class(STRATEGY_ID, ATRTrailingStopStrategy)
