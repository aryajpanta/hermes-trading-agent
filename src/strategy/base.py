"""Base strategy abstract class defining the strategy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import pandas as pd

from src.strategy.signals import Signal


@dataclass
class Strategy:
    """Configuration data model for a trading strategy.

    Attributes:
        id: Unique identifier for the strategy.
        name: Human-readable name.
        source: Originator or reference for the strategy.
        description: Brief explanation of how the strategy works.
        category: Strategy category (trend, mean_reversion, momentum, breakout, value, growth).
        timeframes: List of applicable timeframes (e.g., ["1d", "1h", "5m"]).
        assets: List of applicable asset types (e.g., ["stocks", "crypto", "forex"]).
        entry_rules: Human-readable entry conditions.
        exit_rules: Human-readable exit conditions.
        stop_loss_pct: Stop loss as a percentage (e.g., 0.02 for 2%).
        take_profit_pct: Take profit as a percentage.
        position_size_pct: Recommended position size as portfolio percentage.
        max_holding_period: Maximum holding period in days (0 = unlimited).
        min_confidence: Minimum confidence threshold to generate a signal (0.0-1.0).
    """

    id: str = ""
    name: str = ""
    source: str = ""
    description: str = ""
    category: str = ""
    timeframes: List[str] = field(default_factory=list)
    assets: List[str] = field(default_factory=list)
    entry_rules: List[str] = field(default_factory=list)
    exit_rules: List[str] = field(default_factory=list)
    stop_loss_pct: float = 0.02
    take_profit_pct: float = 0.06
    position_size_pct: float = 0.05
    max_holding_period: int = 0
    min_confidence: float = 0.5

    def __post_init__(self) -> None:
        """Validate strategy configuration."""
        if not self.id:
            raise ValueError("Strategy id is required")
        if not self.name:
            raise ValueError("Strategy name is required")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError(
                f"min_confidence must be between 0.0 and 1.0, got {self.min_confidence}"
            )
        if self.stop_loss_pct < 0:
            raise ValueError(
                f"stop_loss_pct must be >= 0, got {self.stop_loss_pct}"
            )
        if self.take_profit_pct < 0:
            raise ValueError(
                f"take_profit_pct must be >= 0, got {self.take_profit_pct}"
            )


class BaseStrategy(ABC):
    """Abstract base class for all trading strategies.

    All strategy implementations must inherit from this class and implement:
    - evaluate(): Generate a trading signal from market data.
    - required_indicators(): List the technical indicators needed.
    - minimum_data_points(): Minimum number of bars required.
    """

    def __init__(self, config: Optional[Strategy] = None) -> None:
        """Initialize with optional strategy configuration.

        Args:
            config: Strategy configuration. If None, subclasses must set self.config.
        """
        self.config = config or Strategy()

    @abstractmethod
    def evaluate(self, data: pd.DataFrame) -> Signal:
        """Evaluate strategy on market data and return a signal.

        Args:
            data: DataFrame with columns at minimum: open, high, low, close, volume.
                Index should be datetime. May include additional indicator columns.

        Returns:
            Signal with direction, confidence, and reasoning.
        """
        pass

    @abstractmethod
    def required_indicators(self) -> List[str]:
        """Return list of technical indicator names needed by this strategy.

        Returns:
            List of indicator names (e.g., ["SMA_50", "SMA_200", "RSI_14"]).
        """
        pass

    @abstractmethod
    def minimum_data_points(self) -> int:
        """Return the minimum number of data points (bars) needed.

        Returns:
            Minimum number of bars required for the strategy to produce a valid signal.
        """
        pass

    def validate_data(self, data: pd.DataFrame) -> bool:
        """Validate that data meets minimum requirements.

        Args:
            data: DataFrame to validate.

        Returns:
            True if data is sufficient, False otherwise.
        """
        required_cols = ["open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in data.columns:
                return False
        return len(data) >= self.minimum_data_points()

    def _make_signal(
        self,
        direction: float,
        confidence: float,
        reasoning: str,
        symbol: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Signal:
        """Helper to create a Signal with the strategy's config populated.

        Args:
            direction: Signal direction (-1 to +1).
            confidence: Confidence level (0 to 1).
            reasoning: Human-readable reasoning.
            symbol: Asset symbol.
            metadata: Additional metadata.

        Returns:
            Configured Signal instance.
        """
        return Signal(
            direction=direction,
            confidence=confidence,
            reasoning=reasoning,
            strategy_id=self.config.id,
            symbol=symbol,
            metadata=metadata or {},
        )
