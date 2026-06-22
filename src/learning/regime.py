"""Market regime detection — identifies bull, bear, sideways, and high-volatility states."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd


class MarketRegime(str, Enum):
    """Detected market regime."""

    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
    HIGH_VOLATILITY = "high_volatility"
    UNKNOWN = "unknown"


@dataclass
class RegimeState:
    """Full regime detection result.

    Attributes:
        regime: Detected market regime.
        confidence: Confidence in the detection (0.0-1.0).
        ma_20: 20-day moving average value.
        ma_20_slope: Slope of the 20-day MA (positive = up).
        vix_level: Current VIX level (if available).
        avg_range_pct: Average daily range as percentage.
        detected_at: When the regime was detected.
        reasoning: Human-readable explanation.
    """

    regime: MarketRegime = MarketRegime.UNKNOWN
    confidence: float = 0.0
    ma_20: float = 0.0
    ma_20_slope: float = 0.0
    vix_level: float = 0.0
    avg_range_pct: float = 0.0
    detected_at: datetime = field(default_factory=datetime.utcnow)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "regime": self.regime.value,
            "confidence": self.confidence,
            "ma_20": self.ma_20,
            "ma_20_slope": self.ma_20_slope,
            "vix_level": self.vix_level,
            "avg_range_pct": self.avg_range_pct,
            "detected_at": self.detected_at.isoformat(),
            "reasoning": self.reasoning,
        }


class RegimeDetector:
    """Detects the current market regime from OHLCV data.

    Detection rules:
    - Bull: 20-day MA trending up (slope positive, price above MA).
    - Bear: 20-day MA trending down (slope negative, price below MA).
    - High Volatility: VIX > 25 or average daily range > 3%.
    - Sideways: Range-bound, low volatility, MA slope near zero.

    Usage:
        detector = RegimeDetector()
        state = detector.detect(data, vix=22.5)
    """

    # Thresholds
    MA_PERIOD = 20
    SLOPE_THRESHOLD = 0.001  # Minimum slope to consider trending
    VIX_HIGH_THRESHOLD = 25.0
    RANGE_HIGH_THRESHOLD = 0.03  # 3% average daily range

    def detect(
        self,
        data: pd.DataFrame,
        vix: Optional[float] = None,
        lookback: int = 5,
    ) -> RegimeState:
        """Detect the current market regime.

        Args:
            data: OHLCV DataFrame with datetime index. Must have columns:
                'open', 'high', 'low', 'close', 'volume'.
            vix: Current VIX level. If None, volatility is estimated
                from price data.
            lookback: Number of recent bars to compute MA slope.

        Returns:
            RegimeState with detected regime and metadata.
        """
        if len(data) < self.MA_PERIOD + lookback:
            return RegimeState(
                regime=MarketRegime.UNKNOWN,
                confidence=0.0,
                reasoning=f"Insufficient data: need {self.MA_PERIOD + lookback} bars, got {len(data)}",
            )

        close = data["close"]
        high = data["high"]
        low = data["low"]

        # Compute 20-day MA
        ma_20 = close.rolling(self.MA_PERIOD).mean()
        current_ma = float(ma_20.iloc[-1])

        # Compute MA slope (change over lookback periods)
        ma_values = ma_20.iloc[-lookback:].values
        if len(ma_values) >= 2:
            slope = float((ma_values[-1] - ma_values[0]) / ma_values[0])
        else:
            slope = 0.0

        current_price = float(close.iloc[-1])

        # VIX level
        vix_val = vix if vix is not None else self._estimate_volatility(close)

        # Average daily range
        daily_range = (high - low) / close
        avg_range = float(daily_range.iloc[-20:].mean())

        # Classification logic
        reasoning_parts: List[str] = []
        regime = MarketRegime.UNKNOWN
        confidence = 0.0

        # Check high volatility first (overrides trend detection)
        if vix_val > self.VIX_HIGH_THRESHOLD:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = min(1.0, (vix_val - self.VIX_HIGH_THRESHOLD) / 15.0 + 0.5)
            reasoning_parts.append(
                f"VIX at {vix_val:.1f} exceeds threshold of {self.VIX_HIGH_THRESHOLD}"
            )
        elif avg_range > self.RANGE_HIGH_THRESHOLD:
            regime = MarketRegime.HIGH_VOLATILITY
            confidence = min(1.0, avg_range / self.RANGE_HIGH_THRESHOLD * 0.7)
            reasoning_parts.append(
                f"Average daily range {avg_range:.2%} exceeds {self.RANGE_HIGH_THRESHOLD:.2%}"
            )
        elif abs(slope) < self.SLOPE_THRESHOLD:
            # MA slope near zero — sideways
            regime = MarketRegime.SIDEWAYS
            confidence = max(0.3, 1.0 - abs(slope) / self.SLOPE_THRESHOLD)
            reasoning_parts.append(
                f"20-day MA slope ({slope:.6f}) near zero — range-bound"
            )
        elif slope > self.SLOPE_THRESHOLD and current_price > current_ma:
            regime = MarketRegime.BULL
            confidence = min(1.0, 0.5 + slope * 50)
            reasoning_parts.append(
                f"20-day MA trending up (slope {slope:.6f}), "
                f"price {current_price:.2f} above MA {current_ma:.2f}"
            )
        elif slope < -self.SLOPE_THRESHOLD and current_price < current_ma:
            regime = MarketRegime.BEAR
            confidence = min(1.0, 0.5 + abs(slope) * 50)
            reasoning_parts.append(
                f"20-day MA trending down (slope {slope:.6f}), "
                f"price {current_price:.2f} below MA {current_ma:.2f}"
            )
        else:
            # Mixed signals — classify as sideways with lower confidence
            regime = MarketRegime.SIDEWAYS
            confidence = 0.3
            reasoning_parts.append(
                f"Mixed signals: MA slope {slope:.6f}, "
                f"price vs MA position ambiguous"
            )

        reasoning_parts.append(
            f"VIX: {vix_val:.1f}, Avg range: {avg_range:.2%}"
        )

        return RegimeState(
            regime=regime,
            confidence=confidence,
            ma_20=current_ma,
            ma_20_slope=slope,
            vix_level=vix_val,
            avg_range_pct=avg_range,
            detected_at=datetime.utcnow(),
            reasoning="; ".join(reasoning_parts),
        )

    def detect_multi_asset(
        self,
        assets: Dict[str, pd.DataFrame],
        vix: Optional[float] = None,
    ) -> Dict[str, RegimeState]:
        """Detect regime for multiple assets.

        Args:
            assets: Dictionary mapping symbol -> OHLCV DataFrame.
            vix: Current VIX level.

        Returns:
            Dictionary mapping symbol -> RegimeState.
        """
        results: Dict[str, RegimeState] = {}
        for symbol, data in assets.items():
            results[symbol] = self.detect(data, vix=vix)
        return results

    @staticmethod
    def _estimate_volatility(close: pd.Series) -> float:
        """Estimate VIX-equivalent from historical volatility.

        Uses the annualized standard deviation of log returns,
        scaled to approximate VIX units.

        Args:
            close: Price series.

        Returns:
            Estimated VIX-equivalent level.
        """
        if len(close) < 20:
            return 15.0  # Default moderate volatility

        log_returns = np.log(close / close.shift(1)).dropna()
        recent = log_returns.iloc[-20:]
        daily_vol = float(recent.std())
        annualized_vol = float(daily_vol * np.sqrt(252)) * 100  # Convert to percentage
        return float(annualized_vol)
