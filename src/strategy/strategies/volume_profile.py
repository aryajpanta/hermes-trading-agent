"""Volume Profile — Identify key support/resistance from volume distribution.

Buy near high-volume support (POC/VA boundary), sell near high-volume resistance.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "volume_profile"


class VolumeProfileStrategy(BaseStrategy):
    """Volume Profile strategy — trade based on volume-at-price analysis."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Volume Profile",
                source="Market profile theory",
                description="Identify key price levels from volume distribution. Buy at support, sell at resistance.",
                category="breakout",
                timeframes=["1d", "4h"],
                assets=["stocks", "crypto"],
                entry_rules=[
                    "Price approaches Point of Control (POC) from above (support)",
                    "Price breaks above Value Area High (VAH) on volume",
                    "Volume profile shows P-shaped or b-shaped distribution",
                ],
                exit_rules=[
                    "Price reaches next high-volume node",
                    "Price falls back below Value Area Low (VAL)",
                    "Volume dries up near target level",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                position_size_pct=0.05,
                max_holding_period=20,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["VolumeProfile_POC", "VolumeProfile_VAH", "VolumeProfile_VAL"]

    def minimum_data_points(self) -> int:
        return 50

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        high = data["high"]
        low = data["low"]
        volume = data["volume"].astype(float)

        # Approximate volume profile from OHLCV data
        # Create price bins and assign volume to each
        period_data = data.tail(50)
        price_min = period_data["low"].min()
        price_max = period_data["high"].max()

        if price_max == price_min:
            return self._make_signal(0.0, 0.3, "Insufficient price range for volume profile.")

        num_bins = 20
        bin_edges = np.linspace(price_min, price_max, num_bins + 1)
        bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
        volume_at_price = np.zeros(num_bins)

        for _, row in period_data.iterrows():
            bar_range = row["high"] - row["low"]
            if bar_range == 0:
                # Assign all volume to the single price
                idx = np.searchsorted(bin_edges[1:], row["close"], side="right")
                idx = min(idx, num_bins - 1)
                volume_at_price[idx] += row["volume"]
            else:
                # Distribute volume across the bar range
                for i, center in enumerate(bin_centers):
                    if row["low"] <= center <= row["high"]:
                        volume_at_price[i] += row["volume"] / max(1, num_bins // 3)

        # Point of Control (highest volume price)
        poc_idx = np.argmax(volume_at_price)
        poc = bin_centers[poc_idx]

        # Value Area (70% of total volume)
        total_vol = volume_at_price.sum()
        if total_vol == 0:
            return self._make_signal(0.0, 0.3, "No volume data available.")

        sorted_indices = np.argsort(volume_at_price)[::-1]
        cumulative = 0.0
        va_indices = []
        for idx in sorted_indices:
            cumulative += volume_at_price[idx]
            va_indices.append(idx)
            if cumulative >= total_vol * 0.7:
                break

        vah = max(bin_centers[i] for i in va_indices)
        val = min(bin_centers[i] for i in va_indices)

        current_price = close.iloc[-1]

        # Buy near support (POC or VAL from above)
        if val < current_price < poc and (poc - current_price) / poc < 0.02:
            return self._make_signal(
                direction=1.0,
                confidence=0.7,
                reasoning=f"Price ({current_price:.2f}) near POC support ({poc:.2f}). Value area: {val:.2f}-{vah:.2f}.",
                metadata={"poc": poc, "vah": vah, "val": val},
            )

        # Breakout above VAH
        if current_price > vah:
            prev_price = close.iloc[-2]
            if prev_price <= vah:
                return self._make_signal(
                    direction=1.0,
                    confidence=0.65,
                    reasoning=f"Price ({current_price:.2f}) broke above VAH ({vah:.2f}). Bullish breakout.",
                    metadata={"poc": poc, "vah": vah, "val": val},
                )

        # Rejection from VAH
        if current_price < vah:
            prev_price = close.iloc[-2]
            if prev_price >= vah:
                return self._make_signal(
                    direction=-0.5,
                    confidence=0.5,
                    reasoning=f"Price ({current_price:.2f}) rejected at VAH ({vah:.2f}). Falling back into value area.",
                    metadata={"poc": poc, "vah": vah, "val": val},
                )

        return self._make_signal(0.0, 0.3, f"Price within value area ({val:.2f}-{vah:.2f}). POC: {poc:.2f}.", metadata={"poc": poc, "vah": vah, "val": val})


register_strategy_class(STRATEGY_ID, VolumeProfileStrategy)
