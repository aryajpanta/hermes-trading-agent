"""Position sizing — Kelly Criterion and fixed fractional methods."""

from dataclasses import dataclass
from typing import Optional

from src.decision.models import RiskConfig


@dataclass
class PositionSizeResult:
    """Result of position sizing calculation.

    Attributes:
        size_pct: Recommended position size as fraction of portfolio.
        method: Which method was used ("kelly", "fixed_fractional", "capped").
        kelly_fraction: Raw Kelly fraction before capping.
        risk_amount: Dollar risk per share (for stop-loss sizing).
    """

    size_pct: float = 0.0
    method: str = "fixed_fractional"
    kelly_fraction: float = 0.0
    risk_amount: float = 0.0


def kelly_criterion(
    win_rate: float,
    avg_win: float,
    avg_loss: float,
    fractional: float = 0.25,
) -> float:
    """Calculate the Kelly Criterion position size.

    The Kelly Criterion optimizes long-run growth rate:
        f* = (p * b - q) / b
    where p = win probability, q = 1 - p, b = avg_win / avg_loss.

    We use fractional Kelly (typically 0.25) for safety.

    Args:
        win_rate: Probability of a winning trade (0.0–1.0).
        avg_win: Average winning trade return (positive).
        avg_loss: Average losing trade return (positive, as absolute value).
        fractional: Fraction of full Kelly to use (0.0–1.0).

    Returns:
        Kelly fraction (0.0 to fractional * 1.0).
    """
    if win_rate <= 0 or win_rate >= 1:
        return 0.0
    if avg_loss <= 0 or avg_win <= 0:
        return 0.0

    p = win_rate
    q = 1.0 - p
    b = avg_win / avg_loss

    # Kelly formula: f* = (p*b - q) / b
    full_kelly = (p * b - q) / b

    if full_kelly <= 0:
        return 0.0

    return full_kelly * fractional


def calculate_position_size(
    win_rate: Optional[float] = None,
    avg_win: Optional[float] = None,
    avg_loss: Optional[float] = None,
    risk_config: Optional[RiskConfig] = None,
    stop_distance_pct: float = 0.02,
    portfolio_value: float = 100000.0,
) -> PositionSizeResult:
    """Calculate position size using Kelly Criterion with fixed fractional fallback.

    Args:
        win_rate: Historical win rate (0.0–1.0). If None, uses fixed fractional.
        avg_win: Average winning trade return. If None, uses fixed fractional.
        avg_loss: Average losing trade return. If None, uses fixed fractional.
        risk_config: Risk configuration parameters.
        stop_distance_pct: Distance to stop loss as fraction of entry price.
        portfolio_value: Total portfolio value.

    Returns:
        PositionSizeResult with recommended size.
    """
    if risk_config is None:
        risk_config = RiskConfig()

    # Try Kelly Criterion if performance data is available
    if (
        win_rate is not None
        and avg_win is not None
        and avg_loss is not None
        and win_rate > 0
        and avg_win > 0
        and avg_loss > 0
    ):
        kelly = kelly_criterion(win_rate, avg_win, avg_loss)

        if kelly > 0:
            # Cap at max_position_pct
            capped = min(kelly, risk_config.max_position_pct)
            method = "kelly" if capped == kelly else "capped"

            risk_amount = capped * portfolio_value * stop_distance_pct

            return PositionSizeResult(
                size_pct=capped,
                method=method,
                kelly_fraction=kelly,
                risk_amount=risk_amount,
            )

    # Fixed fractional fallback: risk fixed_risk_per_trade of portfolio
    fixed_size = risk_config.fixed_risk_per_trade
    if stop_distance_pct > 0:
        fixed_size = risk_config.fixed_risk_per_trade / stop_distance_pct

    fixed_size = min(fixed_size, risk_config.max_position_pct)

    risk_amount = fixed_size * portfolio_value * stop_distance_pct

    return PositionSizeResult(
        size_pct=fixed_size,
        method="fixed_fractional",
        kelly_fraction=0.0,
        risk_amount=risk_amount,
    )
