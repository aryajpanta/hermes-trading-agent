"""Performance metrics for backtesting results.

Calculates return, risk, trade, and risk-adjusted metrics
for use by the backtesting engine and reporting modules.
"""

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.strategy.backtester import Trade


# ---------------------------------------------------------------------------
# Return Metrics
# ---------------------------------------------------------------------------

def total_return(equity_curve: pd.Series) -> float:
    """Total return as a decimal (e.g., 0.15 = 15%)."""
    if equity_curve.empty or equity_curve.iloc[0] == 0:
        return 0.0
    return float((equity_curve.iloc[-1] / equity_curve.iloc[0]) - 1.0)


def annualized_return(equity_curve: pd.Series, trading_days: int = 252) -> float:
    """Annualized (CAGR) return as a decimal."""
    if equity_curve.empty or equity_curve.iloc[0] <= 0:
        return 0.0
    tr = (equity_curve.iloc[-1] / equity_curve.iloc[0])
    n_years = len(equity_curve) / trading_days
    if n_years <= 0:
        return 0.0
    return float(tr ** (1.0 / n_years) - 1.0)


def monthly_returns(equity_curve: pd.Series) -> Dict[str, float]:
    """Monthly returns as {YYYY-MM: return_decimal}."""
    if equity_curve.empty:
        return {}
    monthly = equity_curve.resample("ME").last()
    returns: Dict[str, float] = {}
    prev = monthly.iloc[0]
    monthly_list = list(monthly.items())
    for i in range(1, len(monthly_list)):
        idx_val, val = monthly_list[i]
        # Use string formatting to avoid type-inference issues
        label = pd.Timestamp(idx_val).to_period("M").strftime("%Y-%m")  # type: ignore[arg-type]
        returns[label] = float((val / prev) - 1.0) if prev != 0 else 0.0
        prev = val
    return returns


# ---------------------------------------------------------------------------
# Risk Metrics
# ---------------------------------------------------------------------------

def daily_returns(equity_curve: pd.Series) -> pd.Series:
    """Daily simple returns from an equity curve."""
    return equity_curve.pct_change().dropna()


def sharpe_ratio(
    equity_curve: pd.Series,
    risk_free_rate: float = 0.04,
    trading_days: int = 252,
) -> float:
    """Annualized Sharpe ratio."""
    dr = daily_returns(equity_curve)
    if dr.empty or dr.std() == 0:
        return 0.0
    excess = dr.mean() - (risk_free_rate / trading_days)
    return float(excess / dr.std() * np.sqrt(trading_days))


def sortino_ratio(
    equity_curve: pd.Series,
    risk_free_rate: float = 0.04,
    trading_days: int = 252,
) -> float:
    """Annualized Sortino ratio (downside deviation only)."""
    dr = daily_returns(equity_curve)
    if dr.empty:
        return 0.0
    downside = dr[dr < 0]
    if downside.empty or downside.std() == 0:
        return 0.0
    excess = dr.mean() - (risk_free_rate / trading_days)
    return float(excess / downside.std() * np.sqrt(trading_days))


def max_drawdown(equity_curve: pd.Series) -> float:
    """Maximum drawdown as a decimal (always <= 0)."""
    if equity_curve.empty:
        return 0.0
    peak = equity_curve.cummax()
    dd = (equity_curve - peak) / peak
    return float(dd.min())


def volatility(equity_curve: pd.Series, trading_days: int = 252) -> float:
    """Annualized volatility."""
    dr = daily_returns(equity_curve)
    if dr.empty:
        return 0.0
    return float(dr.std() * np.sqrt(trading_days))


# ---------------------------------------------------------------------------
# Trade Metrics
# ---------------------------------------------------------------------------

def win_rate(trades: List[Trade]) -> float:
    """Fraction of trades that are profitable."""
    if not trades:
        return 0.0
    wins = sum(1 for t in trades if t.pnl > 0)
    return wins / len(trades)


def profit_factor(trades: List[Trade]) -> float:
    """Gross profit / gross loss.  Returns inf when there are no losses."""
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    if gross_loss == 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def avg_win_loss(trades: List[Trade]) -> Dict[str, float]:
    """Average winning trade PnL and average losing trade PnL."""
    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl < 0]
    return {
        "avg_win": float(np.mean(wins)) if wins else 0.0,
        "avg_loss": float(np.mean(losses)) if losses else 0.0,
    }


def expectancy(trades: List[Trade]) -> float:
    """Expected value per trade."""
    if not trades:
        return 0.0
    return float(np.mean([t.pnl for t in trades]))


# ---------------------------------------------------------------------------
# Risk-Adjusted Metrics
# ---------------------------------------------------------------------------

def calmar_ratio(
    equity_curve: pd.Series, annualized_ret: Optional[float] = None,
) -> float:
    """Calmar ratio: annualized return / abs(max drawdown)."""
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return 0.0
    ar = annualized_ret if annualized_ret is not None else annualized_return(equity_curve)
    return float(ar / abs(mdd))


def recovery_factor(equity_curve: pd.Series) -> float:
    """Recovery factor: total return / abs(max drawdown)."""
    mdd = max_drawdown(equity_curve)
    if mdd == 0:
        return 0.0
    tr = total_return(equity_curve)
    return float(tr / abs(mdd))


# ---------------------------------------------------------------------------
# Aggregate helper
# ---------------------------------------------------------------------------

def compute_all_metrics(
    equity_curve: pd.Series,
    trades: List[Trade],
    risk_free_rate: float = 0.04,
) -> Dict[str, float]:
    """Compute every metric and return as a flat dictionary."""
    ar = annualized_return(equity_curve)
    awl = avg_win_loss(trades)
    return {
        "total_return": total_return(equity_curve),
        "annualized_return": ar,
        "sharpe_ratio": sharpe_ratio(equity_curve, risk_free_rate),
        "sortino_ratio": sortino_ratio(equity_curve, risk_free_rate),
        "max_drawdown": max_drawdown(equity_curve),
        "volatility": volatility(equity_curve),
        "calmar_ratio": calmar_ratio(equity_curve, ar),
        "recovery_factor": recovery_factor(equity_curve),
        "win_rate": win_rate(trades),
        "profit_factor": profit_factor(trades),
        "avg_win": awl["avg_win"],
        "avg_loss": awl["avg_loss"],
        "expectancy": expectancy(trades),
        "total_trades": len(trades),
    }
