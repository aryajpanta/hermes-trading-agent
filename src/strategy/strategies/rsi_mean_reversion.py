"""RSI Mean Reversion (30/70) — Buy oversold, sell overbought.

Uses the Relative Strength Index to identify overbought (>70) and
oversold (<30) conditions for mean-reversion entries.
"""

from typing import List, Optional

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "rsi_mean_reversion"


def _compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Compute RSI for a price series."""
    delta = series.astype(float).diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


class RSIMeanReversionStrategy(BaseStrategy):
    """RSI Mean Reversion strategy using 14-period RSI."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="RSI Mean Reversion (30/70)",
                source="Welles Wilder",
                description="Buy when RSI < 30 (oversold), sell when RSI > 70 (overbought).",
                category="mean_reversion",
                timeframes=["1d", "4h", "1h"],
                assets=["stocks", "crypto", "forex"],
                entry_rules=[
                    "RSI(14) drops below 30 (oversold condition)",
                    "Price shows signs of reversal (higher low or bullish candle)",
                ],
                exit_rules=[
                    "RSI(14) rises above 70 (overbought condition)",
                    "RSI crosses back above 50 from oversold",
                ],
                stop_loss_pct=0.03,
                take_profit_pct=0.06,
                position_size_pct=0.05,
                max_holding_period=10,
                min_confidence=0.55,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["RSI_14"]

    def minimum_data_points(self) -> int:
        return 30

    def evaluate(self, data: pd.DataFrame) -> Signal:
        close = data["close"]
        rsi = _compute_rsi(close, 14)

        current_rsi = rsi.iloc[-1]
        prev_rsi = rsi.iloc[-2]

        if np.isnan(current_rsi):
            return self._make_signal(0.0, 0.0, "RSI not yet available.")

        # Buy: RSI crosses below 30 or is deeply oversold
        if current_rsi < 30:
            if current_rsi < prev_rsi:
                confidence = min(0.9, 0.7 + (30 - current_rsi) / 100)
                return self._make_signal(
                    direction=1.0,
                    confidence=confidence,
                    reasoning=f"RSI oversold at {current_rsi:.1f} (below 30). Mean reversion buy.",
                    metadata={"rsi": current_rsi},
                )
            # RSI turning up from oversold
            if prev_rsi < 30 and current_rsi > prev_rsi:
                return self._make_signal(
                    direction=0.8,
                    confidence=0.7,
                    reasoning=f"RSI bouncing from {prev_rsi:.1f} to {current_rsi:.1f}. Early reversal.",
                    metadata={"rsi": current_rsi},
                )

        # Sell: RSI crosses above 70 or is deeply overbought
        if current_rsi > 70:
            if current_rsi > prev_rsi:
                confidence = min(0.9, 0.7 + (current_rsi - 70) / 100)
                return self._make_signal(
                    direction=-1.0,
                    confidence=confidence,
                    reasoning=f"RSI overbought at {current_rsi:.1f} (above 70). Mean reversion sell.",
                    metadata={"rsi": current_rsi},
                )
            if prev_rsi > 70 and current_rsi < prev_rsi:
                return self._make_signal(
                    direction=-0.8,
                    confidence=0.7,
                    reasoning=f"RSI falling from {prev_rsi:.1f} to {current_rsi:.1f}. Early reversal.",
                    metadata={"rsi": current_rsi},
                )

        # Weak signals in neutral zone
        if 30 <= current_rsi <= 40:
            return self._make_signal(0.3, 0.4, f"RSI near oversold zone at {current_rsi:.1f}.", metadata={"rsi": current_rsi})
        if 60 <= current_rsi <= 70:
            return self._make_signal(-0.3, 0.4, f"RSI near overbought zone at {current_rsi:.1f}.", metadata={"rsi": current_rsi})

        return self._make_signal(0.0, 0.3, f"RSI neutral at {current_rsi:.1f}. No signal.", metadata={"rsi": current_rsi})


register_strategy_class(STRATEGY_ID, RSIMeanReversionStrategy)
