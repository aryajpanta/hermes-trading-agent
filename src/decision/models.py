"""Data models for the Decision Engine."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class Direction(str, Enum):
    """Trade direction."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class RiskConfig:
    """Risk management configuration.

    Attributes:
        max_position_pct: Maximum position size as fraction of portfolio.
        max_portfolio_risk: Maximum daily portfolio loss as fraction.
        max_correlated_positions: Max positions in correlated assets.
        min_confidence: Minimum aggregate confidence to generate a signal.
        min_strategies_agreeing: Minimum strategies that must agree.
        max_holding_period_days: Maximum holding period in days.
        stop_loss_atr_multiple: ATR multiple for stop-loss placement.
        fixed_risk_per_trade: Fixed fractional risk per trade (fallback).
    """

    max_position_pct: float = 0.05
    max_portfolio_risk: float = 0.02
    max_correlated_positions: int = 3
    min_confidence: float = 0.6
    min_strategies_agreeing: int = 2
    max_holding_period_days: int = 30
    stop_loss_atr_multiple: float = 2.0
    fixed_risk_per_trade: float = 0.01


@dataclass
class TradeRecommendation:
    """A trade recommendation produced by the decision engine.

    Attributes:
        symbol: Asset ticker symbol.
        direction: BUY, SELL, or HOLD.
        confidence: Aggregate confidence score (0.0–1.0).
        strategies_agreeing: Strategy IDs that agree with the direction.
        strategies_disagreeing: Strategy IDs that disagree.
        entry_price: Recommended entry price.
        stop_loss: Stop-loss price level.
        take_profit: Take-profit price level.
        position_size_pct: Recommended position size as portfolio percentage.
        risk_reward_ratio: Risk/reward ratio.
        timestamp: When the recommendation was generated.
        reasoning: Human-readable explanation.
    """

    symbol: str = ""
    direction: Direction = Direction.HOLD
    confidence: float = 0.0
    strategies_agreeing: List[str] = field(default_factory=list)
    strategies_disagreeing: List[str] = field(default_factory=list)
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size_pct: float = 0.0
    risk_reward_ratio: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "direction": self.direction.value,
            "confidence": self.confidence,
            "strategies_agreeing": self.strategies_agreeing,
            "strategies_disagreeing": self.strategies_disagreeing,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "position_size_pct": self.position_size_pct,
            "risk_reward_ratio": self.risk_reward_ratio,
            "timestamp": self.timestamp.isoformat(),
            "reasoning": self.reasoning,
        }


@dataclass
class PortfolioPosition:
    """Represents an open position in the portfolio.

    Attributes:
        symbol: Asset ticker.
        direction: Position direction.
        entry_price: Entry price.
        current_price: Current market price.
        size_pct: Position size as fraction of portfolio.
        entry_date: When the position was opened.
        sector: Asset sector/industry for correlation checks.
    """

    symbol: str = ""
    direction: Direction = Direction.BUY
    entry_price: float = 0.0
    current_price: float = 0.0
    size_pct: float = 0.0
    entry_date: datetime = field(default_factory=datetime.utcnow)
    sector: str = "unknown"


@dataclass
class PortfolioState:
    """Overall portfolio state for risk checks.

    Attributes:
        positions: List of open positions.
        daily_pnl_pct: Today's P&L as fraction of portfolio.
        total_exposure_pct: Total portfolio exposure as fraction.
    """

    positions: List[PortfolioPosition] = field(default_factory=list)
    daily_pnl_pct: float = 0.0
    total_exposure_pct: float = 0.0


@dataclass
class StrategyPerformance:
    """Historical performance record for a strategy.

    Attributes:
        strategy_id: Strategy identifier.
        win_rate: Fraction of winning trades.
        profit_factor: Profit factor (gross profits / gross losses).
        sharpe_ratio: Sharpe ratio.
        total_trades: Number of trades taken.
    """

    strategy_id: str = ""
    win_rate: float = 0.5
    profit_factor: float = 1.0
    sharpe_ratio: float = 0.0
    total_trades: int = 0

    @property
    def weight(self) -> float:
        """Compute a normalized weight for this strategy's signals.

        Combines win rate, profit factor, and Sharpe into a single weight.
        Clamps to [0.1, 2.0] so no strategy is zeroed out or dominates.
        High performers can have weight > 1.0 to amplify their signal.
        """
        w = (
            0.4 * self.win_rate
            + 0.3 * min(self.profit_factor / 2.0, 1.0)
            + 0.3 * min(max(self.sharpe_ratio / 2.0, 0.0), 1.0)
        )
        # Scale [0, 1] -> [0, 2] so high performers amplify their signal
        return max(0.1, min(w * 2.0, 2.0))


@dataclass
class DecisionLog:
    """Audit log entry for a single decision.

    Attributes:
        timestamp: When the decision was made.
        symbol: Asset symbol analyzed.
        input_data: Snapshot of input signals.
        strategy_signals: Individual strategy signals.
        aggregated_direction: Aggregated signal direction.
        aggregated_confidence: Aggregated confidence.
        confidence_check: Whether confidence threshold was met.
        agreement_check: Whether agreement threshold was met.
        risk_checks: Results of risk management checks.
        recommendation: Final recommendation (if any).
        reasoning: Human-readable reasoning.
    """

    timestamp: datetime = field(default_factory=datetime.utcnow)
    symbol: str = ""
    input_data: Dict[str, Any] = field(default_factory=dict)
    strategy_signals: List[Dict[str, Any]] = field(default_factory=list)
    aggregated_direction: float = 0.0
    aggregated_confidence: float = 0.0
    confidence_check: bool = False
    agreement_check: bool = False
    risk_checks: Dict[str, Any] = field(default_factory=dict)
    recommendation: Optional[TradeRecommendation] = None
    reasoning: str = ""
