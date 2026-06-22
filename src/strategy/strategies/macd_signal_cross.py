"""MACD Signal Line Cross — Momentum strategy by Gerald Appel.

Buy when MACD line crosses above signal line.
Sell when MACD line crosses below signal line.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "macd_signal_cross"


class MACDSignalCrossStrategy(BaseStrategy):
    """MACD Signal Line Crossover strategy."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="MACD Signal Line Cross",
                source="Gerald Appel",
                description="Buy on MACD bullish crossover, sell on bearish crossover.",
                category="momentum",
                timeframes=["1d", "4h", "1h"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "MACD line crosses above signal line (bullish crossover)",
                    "MACD histogram turns positive",
                    "Histogram is increasing (momentum acceleration)",
                ],
                exit_rules=[
                    "MACD line crosses below signal line (bearish crossover)",
                    "MACD histogram turns negative",
                    "Histogram is decreasing (momentum deceleration)",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.08,
                position_size_pct=0.05,
                max_holding_period=20,
                min_confidence=0.55,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["MACD", "MACD_Signal", "MACD_Histogram"]

    def minimum_data_points(self) -> int:
        return 35

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]

        ema_12 = close.ewm(span=12, adjust=False).mean()
        ema_26 = close.ewm(span=26, adjust=False).mean()
        macd_line = ema_12 - ema_26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        histogram = macd_line - signal_line

        current_macd = macd_line.iloc[-1]
        current_signal = signal_line.iloc[-1]
        current_hist = histogram.iloc[-1]
        prev_macd = macd_line.iloc[-2]
        prev_signal = signal_line.iloc[-2]

        # Bullish crossover
        if prev_macd <= prev_signal and current_macd > current_signal:
            confidence = min(0.85, 0.6 + abs(current_hist) / abs(current_macd) * 0.3 if current_macd != 0 else 0.7)
            return self._make_signal(
                direction=1.0,
                confidence=confidence,
                reasoning=f"MACD bullish crossover: MACD ({current_macd:.4f}) crossed above signal ({current_signal:.4f}).",
                metadata={"macd": current_macd, "signal": current_signal, "histogram": current_hist},
            )

        # Bearish crossover
        if prev_macd >= prev_signal and current_macd < current_signal:
            confidence = min(0.85, 0.6 + abs(current_hist) / abs(current_macd) * 0.3 if current_macd != 0 else 0.7)
            return self._make_signal(
                direction=-1.0,
                confidence=confidence,
                reasoning=f"MACD bearish crossover: MACD ({current_macd:.4f}) crossed below signal ({current_signal:.4f}).",
                metadata={"macd": current_macd, "signal": current_signal, "histogram": current_hist},
            )

        prev_hist = histogram.iloc[-2]

        # Histogram increasing positive
        if current_hist > 0 and current_hist > prev_hist:
            return self._make_signal(0.5, 0.5, f"MACD histogram positive and increasing ({current_hist:.4f}).", metadata={"histogram": current_hist})

        # Histogram decreasing negative
        if current_hist < 0 and current_hist < prev_hist:
            return self._make_signal(-0.5, 0.5, f"MACD histogram negative and decreasing ({current_hist:.4f}).", metadata={"histogram": current_hist})

        return self._make_signal(0.0, 0.3, f"MACD neutral. Histogram at {current_hist:.4f}.", metadata={"histogram": current_hist})


register_strategy_class(STRATEGY_ID, MACDSignalCrossStrategy)
