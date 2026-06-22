"""Order Flow Imbalance — Institutional momentum strategy.

Identifies large order imbalances between buyers and sellers
to detect smart money accumulation or distribution.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "order_flow_imbalance"


class OrderFlowImbalanceStrategy(BaseStrategy):
    """Order Flow Imbalance strategy — detect institutional buying/selling pressure."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Order Flow Imbalance",
                source="Prop trading",
                description="Detect buyer/seller imbalance using volume and price action analysis.",
                category="momentum",
                timeframes=["5m", "15m", "1h"],
                assets=["stocks", "crypto", "futures"],
                entry_rules=[
                    "Positive volume delta > 2x average (buying pressure)",
                    "Price closes in upper 20% of bar range with high volume",
                    "Successive higher closes with increasing volume",
                    "Large volume bar with narrow range (accumulation)",
                ],
                exit_rules=[
                    "Negative volume delta appears",
                    "Price closes in lower 20% of bar range on high volume",
                    "Volume divergence: price up but volume declining",
                    "Large range bar with decreasing volume (distribution)",
                ],
                stop_loss_pct=0.02,
                take_profit_pct=0.05,
                position_size_pct=0.03,
                max_holding_period=5,
                min_confidence=0.65,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["VolumeDelta", "CVD", "TradeIntensity"]

    def minimum_data_points(self) -> int:
        return 20

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        open_ = data["open"]
        high = data["high"]
        low = data["low"]
        volume = data["volume"].astype(float)

        # Estimate buying/selling volume using close position in bar
        bar_range = high - low
        bar_range_safe = bar_range.replace(0, np.nan)
        close_position = (close - low) / bar_range_safe  # 0=low, 1=high
        close_position = close_position.fillna(0.5)

        buy_volume = volume * close_position
        sell_volume = volume * (1 - close_position)

        # Volume delta (net buying pressure)
        volume_delta = buy_volume - sell_volume
        cumulative_volume_delta = volume_delta.cumsum()

        # Average metrics
        avg_delta = volume_delta.rolling(20).mean()
        avg_volume = volume.rolling(20).mean()

        current_delta = volume_delta.iloc[-1]
        current_avg_delta = avg_delta.iloc[-1]
        current_volume = volume.iloc[-1]
        current_avg_vol = avg_volume.iloc[-1]

        # Bar analysis
        current_close = close.iloc[-1]
        current_open = open_.iloc[-1]
        current_high = high.iloc[-1]
        current_low = low.iloc[-1]
        current_range = current_high - current_low

        vol_ratio = current_volume / current_avg_vol if current_avg_vol > 0 else 1.0
        delta_ratio = current_delta / abs(current_avg_delta) if current_avg_delta != 0 else 0

        # Check recent CVD trend
        cvd_recent = cumulative_volume_delta.iloc[-5:]
        cvd_slope = (cvd_recent.iloc[-1] - cvd_recent.iloc[0]) / len(cvd_recent) if len(cvd_recent) > 1 else 0

        # Strong buying pressure
        if current_delta > 0 and current_delta > current_avg_delta * 1.5:
            confidence = 0.65
            reasons = [f"Strong buying delta ({current_delta:.0f}, {delta_ratio:.1f}x avg)"]

            # Confirmation: close near high of bar
            if current_range > 0 and (current_close - current_low) / current_range > 0.8:
                confidence = min(0.85, confidence + 0.1)
                reasons.append("Close near bar high")

            # Volume confirmation
            if vol_ratio > 1.5:
                confidence = min(0.85, confidence + 0.1)
                reasons.append(f"High volume ({vol_ratio:.1f}x)")

            # CVD confirmation
            if cvd_slope > 0:
                confidence = min(0.85, confidence + 0.05)
                reasons.append("Rising CVD")

            return self._make_signal(1.0, confidence, ". ".join(reasons) + ".", metadata={"volume_delta": current_delta, "vol_ratio": vol_ratio})

        # Strong selling pressure
        if current_delta < 0 and current_delta < current_avg_delta * 1.5:
            confidence = 0.65
            reasons = [f"Selling delta ({current_delta:.0f}, {delta_ratio:.1f}x avg)"]

            if current_range > 0 and (current_high - current_close) / current_range > 0.8:
                confidence = min(0.85, confidence + 0.1)
                reasons.append("Close near bar low")

            if vol_ratio > 1.5:
                confidence = min(0.85, confidence + 0.1)
                reasons.append(f"High volume ({vol_ratio:.1f}x)")

            if cvd_slope < 0:
                confidence = min(0.85, confidence + 0.05)
                reasons.append("Declining CVD")

            return self._make_signal(-1.0, confidence, ". ".join(reasons) + ".", metadata={"volume_delta": current_delta, "vol_ratio": vol_ratio})

        # Volume divergence: price up but CVD declining
        if len(close) > 5:
            price_trend = close.iloc[-1] > close.iloc[-5]
            cvd_trend = cvd_slope > 0
            if price_trend and not cvd_trend:
                return self._make_signal(-0.5, 0.6, "Bearish divergence: price rising but CVD declining. Hidden selling.")
            if not price_trend and cvd_trend:
                return self._make_signal(0.5, 0.6, "Bullish divergence: price falling but CVD rising. Hidden buying.")

        return self._make_signal(0.0, 0.3, f"Order flow neutral. Delta: {current_delta:.0f}, CVD slope: {cvd_slope:.0f}.", metadata={"volume_delta": current_delta})


register_strategy_class(STRATEGY_ID, OrderFlowImbalanceStrategy)
