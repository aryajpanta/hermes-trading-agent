"""Risk management — portfolio-level and per-trade risk checks."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from src.decision.models import Direction, PortfolioPosition, PortfolioState, RiskConfig


@dataclass
class RiskCheckResult:
    """Result of a risk management check.

    Attributes:
        passed: Whether the risk check passed.
        reason: Reason if the check failed.
        checks: Individual check details.
    """

    passed: bool = True
    reason: str = ""
    checks: Dict[str, bool] = field(default_factory=dict)


def check_position_size(
    size_pct: float, risk_config: Optional[RiskConfig] = None
) -> RiskCheckResult:
    """Check if a position size is within risk limits.

    Args:
        size_pct: Proposed position size as fraction of portfolio.
        risk_config: Risk configuration.

    Returns:
        RiskCheckResult indicating pass/fail.
    """
    if risk_config is None:
        risk_config = RiskConfig()

    passed = size_pct <= risk_config.max_position_pct
    return RiskCheckResult(
        passed=passed,
        reason="" if passed else f"Position size {size_pct:.2%} exceeds max {risk_config.max_position_pct:.2%}",
        checks={"position_size": passed},
    )


def check_daily_loss(
    portfolio: PortfolioState, risk_config: Optional[RiskConfig] = None
) -> RiskCheckResult:
    """Check if daily loss limit has been breached.

    Args:
        portfolio: Current portfolio state.
        risk_config: Risk configuration.

    Returns:
        RiskCheckResult indicating pass/fail.
    """
    if risk_config is None:
        risk_config = RiskConfig()

    # Daily P&L is negative when losing
    breached = portfolio.daily_pnl_pct < -risk_config.max_portfolio_risk
    return RiskCheckResult(
        passed=not breached,
        reason=(
            ""
            if not breached
            else f"Daily loss {portfolio.daily_pnl_pct:.2%} exceeds limit {-risk_config.max_portfolio_risk:.2%}"
        ),
        checks={"daily_loss": not breached},
    )


def check_correlation(
    symbol: str,
    sector: str,
    portfolio: PortfolioState,
    risk_config: Optional[RiskConfig] = None,
) -> RiskCheckResult:
    """Check if adding a position would exceed correlated position limit.

    Args:
        symbol: Symbol to check.
        sector: Sector of the symbol.
        portfolio: Current portfolio state.
        risk_config: Risk configuration.

    Returns:
        RiskCheckResult indicating pass/fail.
    """
    if risk_config is None:
        risk_config = RiskConfig()

    # Count positions in the same sector (including the proposed one)
    same_sector = sum(
        1 for pos in portfolio.positions if pos.sector == sector
    )

    # Also count positions in the same symbol
    same_symbol = sum(
        1 for pos in portfolio.positions if pos.symbol == symbol
    )

    sector_ok = (same_sector + 1) <= risk_config.max_correlated_positions
    symbol_ok = same_symbol == 0  # No duplicate positions

    passed = sector_ok and symbol_ok

    reasons = []
    if not sector_ok:
        reasons.append(
            f"Sector '{sector}' already has {same_sector} positions "
            f"(max {risk_config.max_correlated_positions})"
        )
    if not symbol_ok:
        reasons.append(f"Already holding position in {symbol}")

    return RiskCheckResult(
        passed=passed,
        reason="; ".join(reasons) if reasons else "",
        checks={"correlation_sector": sector_ok, "duplicate_symbol": symbol_ok},
    )


def check_confidence(
    confidence: float, risk_config: Optional[RiskConfig] = None
) -> RiskCheckResult:
    """Check if aggregate confidence meets the threshold.

    Args:
        confidence: Aggregate confidence score (0.0–1.0).
        risk_config: Risk configuration.

    Returns:
        RiskCheckResult indicating pass/fail.
    """
    if risk_config is None:
        risk_config = RiskConfig()

    passed = confidence >= risk_config.min_confidence
    return RiskCheckResult(
        passed=passed,
        reason=(
            ""
            if passed
            else f"Confidence {confidence:.2f} below minimum {risk_config.min_confidence:.2f}"
        ),
        checks={"confidence_threshold": passed},
    )


def check_agreement(
    agreeing_count: int, risk_config: Optional[RiskConfig] = None
) -> RiskCheckResult:
    """Check if enough strategies agree.

    Args:
        agreeing_count: Number of strategies agreeing.
        risk_config: Risk configuration.

    Returns:
        RiskCheckResult indicating pass/fail.
    """
    if risk_config is None:
        risk_config = RiskConfig()

    passed = agreeing_count >= risk_config.min_strategies_agreeing
    return RiskCheckResult(
        passed=passed,
        reason=(
            ""
            if passed
            else f"Only {agreeing_count} strategies agree "
            f"(min {risk_config.min_strategies_agreeing})"
        ),
        checks={"agreement_threshold": passed},
    )


def run_all_risk_checks(
    size_pct: float,
    confidence: float,
    agreeing_count: int,
    symbol: str,
    sector: str,
    portfolio: PortfolioState,
    risk_config: Optional[RiskConfig] = None,
) -> RiskCheckResult:
    """Run all risk management checks and return combined result.

    Args:
        size_pct: Proposed position size.
        confidence: Aggregate confidence.
        agreeing_count: Number of agreeing strategies.
        symbol: Symbol being considered.
        sector: Sector of the symbol.
        portfolio: Current portfolio state.
        risk_config: Risk configuration.

    Returns:
        Combined RiskCheckResult. passed=True only if ALL checks pass.
    """
    checks = [
        check_position_size(size_pct, risk_config),
        check_confidence(confidence, risk_config),
        check_agreement(agreeing_count, risk_config),
        check_daily_loss(portfolio, risk_config),
        check_correlation(symbol, sector, portfolio, risk_config),
    ]

    all_passed = all(c.passed for c in checks)
    all_checks: Dict[str, bool] = {}
    failed_reasons: List[str] = []

    for c in checks:
        all_checks.update(c.checks)
        if not c.passed and c.reason:
            failed_reasons.append(c.reason)

    return RiskCheckResult(
        passed=all_passed,
        reason="; ".join(failed_reasons) if failed_reasons else "",
        checks=all_checks,
    )
