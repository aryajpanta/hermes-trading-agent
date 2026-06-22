"""Moving Average Crossover (50/200) — Classic trend-following strategy.

Buy when the 50-period SMA crosses above the 200-period SMA (golden cross).
Sell when the 50-period SMA crosses below the 200-period SMA (death cross).
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "ma_crossover_50_200"


class MACrossoverStrategy(BaseStrategy):
    """Moving Average Crossover strategy using 50/200 SMA."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Moving Average Crossover (50/200)",
                source="Trend following",
                description="Buy on golden cross (SMA50 > SMA200), sell on death cross.",
                category="trend",
                timeframes=["1d", "1w"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "50-period SMA crosses above 200-period SMA (golden cross)",
                    "Price is above the 200-period SMA",
                ],
                exit_rules=[
                    "50-period SMA crosses below 200-period SMA (death cross)",
                    "Price closes below the 200-period SMA",
                ],
                stop_loss_pct=0.05,
                take_profit_pct=0.15,
                position_size_pct=0.05,
                max_holding_period=0,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["SMA_50", "SMA_200"]

    def minimum_data_points(self) -> int:
        return 200

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        sma_50 = close.rolling(50).mean()
        sma_200 = close.rolling(200).mean()

        current_price = close.iloc[-1]
        current_sma50 = sma_50.iloc[-1]
        current_sma200 = sma_200.iloc[-1]
        prev_sma50 = sma_50.iloc[-2]
        prev_sma200 = sma_200.iloc[-2]

        # Golden cross: SMA50 crosses above SMA200
        golden_cross = prev_sma50 <= prev_sma200 and current_sma50 > current_sma200
        # Death cross: SMA50 crosses below SMA200
        death_cross = prev_sma50 >= prev_sma200 and current_sma50 < current_sma200

        if golden_cross and current_price > current_sma200:
            spread = (current_sma50 - current_sma200) / current_sma200
            confidence = min(0.9, 0.6 + spread * 5)
            return self._make_signal(
                direction=1.0,
                confidence=confidence,
                reasoning=f"Golden cross: SMA50 ({current_sma50:.2f}) crossed above SMA200 ({current_sma200:.2f}). Price ({current_price:.2f}) above SMA200.",
                metadata={"sma_50": current_sma50, "sma_200": current_sma200},
            )

        if death_cross and current_price < current_sma200:
            spread = (current_sma200 - current_sma50) / current_sma200
            confidence = min(0.9, 0.6 + spread * 5)
            return self._make_signal(
                direction=-1.0,
                confidence=confidence,
                reasoning=f"Death cross: SMA50 ({current_sma50:.2f}) crossed below SMA200 ({current_sma200:.2f}). Price ({current_price:.2f}) below SMA200.",
                metadata={"sma_50": current_sma50, "sma_200": current_sma200},
            )

        # Ongoing trend signal
        if current_sma50 > current_sma200 and current_price > current_sma50:
            confidence = 0.5
            return self._make_signal(
                direction=0.5,
                confidence=confidence,
                reasoning="Uptrend: SMA50 > SMA200, price above both. No new cross.",
                metadata={"sma_50": current_sma50, "sma_200": current_sma200},
            )

        if current_sma50 < current_sma200 and current_price < current_sma50:
            confidence = 0.5
            return self._make_signal(
                direction=-0.5,
                confidence=confidence,
                reasoning="Downtrend: SMA50 < SMA200, price below both. No new cross.",
                metadata={"sma_50": current_sma50, "sma_200": current_sma200},
            )

        return self._make_signal(
            direction=0.0,
            confidence=0.3,
            reasoning="No clear signal — MAs are intertwined or no crossover.",
            metadata={"sma_50": current_sma50, "sma_200": current_sma200},
        )


register_strategy_class(STRATEGY_ID, MACrossoverStrategy)
