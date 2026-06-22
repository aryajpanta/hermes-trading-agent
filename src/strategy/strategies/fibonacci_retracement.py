"""Fibonacci Retracement — Support/resistance at key Fibonacci levels.

Buy at 38.2% or 61.8% retracement support, sell near previous high.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "fibonacci_retracement"


class FibonacciRetracementStrategy(BaseStrategy):
    """Fibonacci Retracement strategy — trade bounces at key fib levels."""

    FIB_LEVELS = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Fibonacci Retracement",
                source="Leonardo Fibonacci",
                description="Buy at key Fibonacci retracement levels (38.2%, 50%, 61.8%), sell near extension targets.",
                category="breakout",
                timeframes=["1d", "4h", "1h"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "Price retraces to 38.2% or 61.8% Fibonacci level",
                    "Price shows reversal candle at fib level",
                    "Volume confirms the bounce at the level",
                ],
                exit_rules=[
                    "Price reaches 0% extension (previous high/low)",
                    "Price breaks below 78.6% retracement (invalidation)",
                    "Target at 127.2% or 161.8% extension reached",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.08,
                position_size_pct=0.05,
                max_holding_period=30,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["Fib_382", "Fib_500", "Fib_618"]

    def minimum_data_points(self) -> int:
        return 50

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        high = data["high"]
        low = data["low"]

        # Find recent swing high and low (50-bar lookback)
        lookback = min(50, len(data) - 1)
        period_high = high.tail(lookback).max()
        period_low = low.tail(lookback).min()
        swing_range = period_high - period_low

        if swing_range <= 0:
            return self._make_signal(0.0, 0.3, "No price range for Fibonacci analysis.")

        # Calculate Fibonacci levels (retracement from high)
        fib_levels = {}
        for level in self.FIB_LEVELS:
            fib_levels[level] = period_high - (level * swing_range)

        current_price = close.iloc[-1]
        prev_price = close.iloc[-2]

        # Check proximity to key fib levels
        key_levels = [0.382, 0.5, 0.618]
        tolerance = swing_range * 0.01  # 1% of range

        for level in key_levels:
            fib_price = fib_levels[level]

            # Price near fib level from above (support)
            if abs(current_price - fib_price) < tolerance:
                # Bullish reversal candle (close > open)
                current_close = close.iloc[-1]
                current_open = data["open"].iloc[-1]
                is_bullish = current_close > current_open

                if is_bullish and current_price > prev_price:
                    confidence = 0.7 if level == 0.618 else 0.65
                    return self._make_signal(
                        direction=1.0,
                        confidence=confidence,
                        reasoning=f"Price ({current_price:.2f}) bouncing at {level*100:.1f}% Fib level ({fib_price:.2f}). Bullish reversal candle.",
                        metadata={"fib_level": level, "fib_price": fib_price, "swing_high": period_high, "swing_low": period_low},
                    )

            # Price broke below key support (bearish)
            if level == 0.618:
                if prev_price > fib_price and current_price < fib_price:
                    return self._make_signal(
                        direction=-1.0,
                        confidence=0.7,
                        reasoning=f"Price ({current_price:.2f}) broke below 61.8% Fib support ({fib_price:.2f}). Trend invalidation.",
                        metadata={"fib_level": level, "fib_price": fib_price},
                    )

        # Near 0% (previous high) — potential resistance
        if abs(current_price - period_high) < tolerance and current_price < period_high:
            return self._make_signal(-0.4, 0.5, f"Price ({current_price:.2f}) near previous high ({period_high:.2f}). Potential resistance.")

        # Near 100% (previous low) — potential support
        if abs(current_price - period_low) < tolerance and current_price > period_low:
            return self._make_signal(0.4, 0.5, f"Price ({current_price:.2f}) near previous low ({period_low:.2f}). Potential support.")

        # Report current position relative to fib levels
        position_in_range = (current_price - period_low) / swing_range if swing_range > 0 else 0.5
        return self._make_signal(0.0, 0.3, f"Price at {position_in_range:.1%} of swing range. Key fibs: 38.2%={fib_levels[0.382]:.2f}, 61.8%={fib_levels[0.618]:.2f}.")


register_strategy_class(STRATEGY_ID, FibonacciRetracementStrategy)
