"""Turtle Trading System — Trend-following system by Richard Dennis.

Buy on 20-day breakout (entry), exit on 10-day breakout in opposite direction.
Position sizing based on ATR (N).
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "turtle_trading"


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 20) -> pd.Series:
    """Compute Average True Range."""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=1).mean()


class TurtleTradingStrategy(BaseStrategy):
    """Turtle Trading System — classic trend-following breakout strategy."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Turtle Trading System",
                source="Richard Dennis",
                description="Enter on 20-day high breakout, exit on 10-day low breakout. ATR-based position sizing.",
                category="trend",
                timeframes=["1d", "1w"],
                assets=["stocks", "crypto", "forex", "commodities"],
                entry_rules=[
                    "Price breaks above 20-day high",
                    "ATR(20) confirms sufficient volatility",
                    "Position size = 1% risk / (2 * ATR)",
                ],
                exit_rules=[
                    "Price breaks below 10-day low",
                    "Trailing stop at 2 * ATR from entry",
                    "System 2: 55-day breakout exit",
                ],
                stop_loss_pct=0.02,
                take_profit_pct=0.10,
                position_size_pct=0.02,
                max_holding_period=0,
                min_confidence=0.65,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["HighestHigh_20", "LowestLow_10", "ATR_20"]

    def minimum_data_points(self) -> int:
        return 25

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        high = data["high"]
        low = data["low"]

        # 20-day and 10-day breakouts
        highest_20 = high.rolling(20).max()
        lowest_10 = low.rolling(10).min()

        atr = _compute_atr(high, low, close, 20)

        current_close = close.iloc[-1]
        prev_close = close.iloc[-2]
        current_high_20 = highest_20.iloc[-2]  # Previous bar's 20-day high
        current_low_10 = lowest_10.iloc[-2]  # Previous bar's 10-day low
        current_atr = atr.iloc[-1]

        # Long entry: price breaks above 20-day high
        if prev_close <= current_high_20 and current_close > current_high_20:
            atr_pct = current_atr / current_close if current_close > 0 else 0
            confidence = min(0.85, 0.6 + atr_pct * 5)
            return self._make_signal(
                direction=1.0,
                confidence=confidence,
                reasoning=f"20-day high breakout: price ({current_close:.2f}) broke above high ({current_high_20:.2f}). ATR: {current_atr:.2f}.",
                metadata={"breakout_level": current_high_20, "atr": current_atr},
            )

        # Short entry: price breaks below 10-day low
        if prev_close >= current_low_10 and current_close < current_low_10:
            atr_pct = current_atr / current_close if current_close > 0 else 0
            confidence = min(0.85, 0.6 + atr_pct * 5)
            return self._make_signal(
                direction=-1.0,
                confidence=confidence,
                reasoning=f"10-day low breakdown: price ({current_close:.2f}) broke below low ({current_low_10:.2f}). ATR: {current_atr:.2f}.",
                metadata={"breakout_level": current_low_10, "atr": current_atr},
            )

        # Close to breakout levels
        if current_high_20 > 0:
            proximity = (current_high_20 - current_close) / current_high_20
            if 0 < proximity < 0.01:
                return self._make_signal(0.4, 0.4, f"Price ({current_close:.2f}) near 20-day high ({current_high_20:.2f}). Watch for breakout.")

        return self._make_signal(0.0, 0.3, f"No breakout. 20d high: {current_high_20:.2f}, 10d low: {current_low_10:.2f}.")


register_strategy_class(STRATEGY_ID, TurtleTradingStrategy)
