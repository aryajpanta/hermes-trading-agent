"""VWAP Reversion — Institutional mean-reversion around VWAP.

Buy when price deviates significantly below VWAP.
Sell when price deviates significantly above VWAP.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "vwap_reversion"


class VWAPReversionStrategy(BaseStrategy):
    """VWAP Reversion strategy — trade mean reversion to Volume Weighted Average Price."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="VWAP Reversion",
                source="Institutional",
                description="Buy when price is significantly below VWAP, sell when above.",
                category="mean_reversion",
                timeframes=["1h", "5m", "15m"],
                assets=["stocks", "crypto"],
                entry_rules=[
                    "Price is > 2 standard deviations below VWAP",
                    "Volume confirms the move (above average)",
                    "Price shows reversal candle near VWAP deviation band",
                ],
                exit_rules=[
                    "Price returns to VWAP",
                    "Price reaches +1 standard deviation above VWAP",
                    "End of trading session (for intraday)",
                ],
                stop_loss_pct=0.02,
                take_profit_pct=0.04,
                position_size_pct=0.03,
                max_holding_period=1,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["VWAP", "VWAP_StdDev"]

    def minimum_data_points(self) -> int:
        return 20

    def evaluate(self, data: pd.DataFrame) -> Signal:
        typical_price = (data["high"] + data["low"] + data["close"]) / 3
        volume = data["volume"].astype(float)

        cumulative_tp_vol = (typical_price * volume).cumsum()
        cumulative_vol = volume.cumsum()

        # Avoid division by zero
        cumulative_vol_safe = cumulative_vol.replace(0, np.nan)
        vwap = cumulative_tp_vol / cumulative_vol_safe

        # Rolling VWAP standard deviation approximation
        vwap_diff = typical_price - vwap
        vwap_std = vwap_diff.rolling(20, min_periods=5).std()

        current_price = data["close"].iloc[-1]
        current_vwap = vwap.iloc[-1]
        current_std = vwap_std.iloc[-1]

        if np.isnan(current_vwap) or np.isnan(current_std) or current_std == 0:
            return self._make_signal(0.0, 0.0, "VWAP data not yet available.")

        deviation = (current_price - current_vwap) / current_std

        avg_volume = volume.rolling(20).mean().iloc[-1]
        current_vol = volume.iloc[-1]
        vol_ratio = current_vol / avg_volume if avg_volume > 0 else 1.0

        # Price significantly below VWAP — buy
        if deviation < -2.0:
            confidence = min(0.85, 0.6 + abs(deviation - 2.0) * 0.1)
            reasoning = f"Price ({current_price:.2f}) is {abs(deviation):.1f} std devs below VWAP ({current_vwap:.2f})."
            if vol_ratio > 1.2:
                confidence = min(0.9, confidence + 0.1)
                reasoning += f" Volume {vol_ratio:.1f}x average confirms."
            return self._make_signal(direction=1.0, confidence=confidence, reasoning=reasoning, metadata={"vwap": current_vwap, "deviation": deviation})

        # Price significantly above VWAP — sell
        if deviation > 2.0:
            confidence = min(0.85, 0.6 + abs(deviation - 2.0) * 0.1)
            reasoning = f"Price ({current_price:.2f}) is {abs(deviation):.1f} std devs above VWAP ({current_vwap:.2f})."
            if vol_ratio > 1.2:
                confidence = min(0.9, confidence + 0.1)
                reasoning += f" Volume {vol_ratio:.1f}x average confirms."
            return self._make_signal(direction=-1.0, confidence=confidence, reasoning=reasoning, metadata={"vwap": current_vwap, "deviation": deviation})

        # Mild deviations
        if -1.0 < deviation < -0.5:
            return self._make_signal(0.4, 0.4, f"Price {abs(deviation):.1f} std devs below VWAP. Mild buy zone.", metadata={"deviation": deviation})
        if 0.5 < deviation < 1.0:
            return self._make_signal(-0.4, 0.4, f"Price {abs(deviation):.1f} std devs above VWAP. Mild sell zone.", metadata={"deviation": deviation})

        return self._make_signal(0.0, 0.3, f"Price near VWAP (deviation: {deviation:.2f}). No clear signal.", metadata={"deviation": deviation})


register_strategy_class(STRATEGY_ID, VWAPReversionStrategy)
