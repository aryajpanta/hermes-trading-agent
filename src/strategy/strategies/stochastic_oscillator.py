"""Stochastic Oscillator — Momentum strategy by George Lane.

Buy when %K crosses above %D in oversold zone.
Sell when %K crosses below %D in overbought zone.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "stochastic_oscillator"


class StochasticOscillatorStrategy(BaseStrategy):
    """Stochastic Oscillator strategy (%K/%D crossover)."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Stochastic Oscillator",
                source="Lane",
                description="Buy when %K crosses above %D below 20, sell when %K crosses below %D above 80.",
                category="momentum",
                timeframes=["1d", "4h", "1h"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "%K crosses above %D in oversold zone (below 20)",
                    "Both %K and %D are below 30",
                    "Stochastic %K turns upward from below 20",
                ],
                exit_rules=[
                    "%K crosses below %D in overbought zone (above 80)",
                    "Both %K and %D are above 70",
                    "Stochastic %K turns downward from above 80",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                position_size_pct=0.05,
                max_holding_period=15,
                min_confidence=0.55,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["Stoch_K", "Stoch_D"]

    def minimum_data_points(self) -> int:
        return 20

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        high = data["high"]
        low = data["low"]

        # 14-period stochastic
        lowest_14 = low.rolling(14).min()
        highest_14 = high.rolling(14).max()
        range_14 = highest_14 - lowest_14

        # Avoid division by zero
        range_14_safe = range_14.replace(0, np.nan)
        fast_k = ((close - lowest_14) / range_14_safe) * 100
        fast_k = fast_k.fillna(50)

        # %D = 3-period SMA of %K
        slow_k = fast_k.rolling(3).mean()
        slow_d = slow_k.rolling(3).mean()

        current_k = slow_k.iloc[-1]
        current_d = slow_d.iloc[-1]
        prev_k = slow_k.iloc[-2]
        prev_d = slow_d.iloc[-2]

        if np.isnan(current_k) or np.isnan(current_d):
            return self._make_signal(0.0, 0.0, "Stochastic not yet available.")

        # Bullish crossover in oversold zone
        if prev_k <= prev_d and current_k > current_d and current_k < 30:
            confidence = min(0.85, 0.65 + (30 - current_k) / 100)
            return self._make_signal(
                direction=1.0,
                confidence=confidence,
                reasoning=f"Stochastic bullish crossover in oversold zone: %K ({current_k:.1f}) crossed above %D ({current_d:.1f}).",
                metadata={"stoch_k": current_k, "stoch_d": current_d},
            )

        # Bearish crossover in overbought zone
        if prev_k >= prev_d and current_k < current_d and current_k > 70:
            confidence = min(0.85, 0.65 + (current_k - 70) / 100)
            return self._make_signal(
                direction=-1.0,
                confidence=confidence,
                reasoning=f"Stochastic bearish crossover in overbought zone: %K ({current_k:.1f}) crossed below %D ({current_d:.1f}).",
                metadata={"stoch_k": current_k, "stoch_d": current_d},
            )

        # Mild signals
        if current_k < 20 and current_k > prev_k:
            return self._make_signal(0.5, 0.5, f"Stochastic oversold (%K={current_k:.1f}), turning up.", metadata={"stoch_k": current_k})
        if current_k > 80 and current_k < prev_k:
            return self._make_signal(-0.5, 0.5, f"Stochastic overbought (%K={current_k:.1f}), turning down.", metadata={"stoch_k": current_k})

        return self._make_signal(0.0, 0.3, f"Stochastic neutral: %K={current_k:.1f}, %D={current_d:.1f}.", metadata={"stoch_k": current_k, "stoch_d": current_d})


register_strategy_class(STRATEGY_ID, StochasticOscillatorStrategy)
