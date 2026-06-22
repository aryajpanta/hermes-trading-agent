"""Benchmark comparison for paper trading portfolio."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class BenchmarkResult:
    """Performance of a single benchmark."""

    name: str = ""
    total_return: float = 0.0
    annualized_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    equity_curve: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
        }


@dataclass
class BenchmarkComparison:
    """Full comparison of portfolio vs benchmarks with alpha/beta."""

    portfolio_return: float = 0.0
    portfolio_sharpe: float = 0.0
    benchmarks: Dict[str, BenchmarkResult] = field(default_factory=dict)
    alpha: Dict[str, float] = field(default_factory=dict)
    beta: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "portfolio_return": self.portfolio_return,
            "portfolio_sharpe": self.portfolio_sharpe,
            "benchmarks": {k: v.to_dict() for k, v in self.benchmarks.items()},
            "alpha": self.alpha,
            "beta": self.beta,
        }


def _calc_total_return(curve: List[float]) -> float:
    """Total return from an equity curve."""
    if len(curve) < 2 or curve[0] == 0:
        return 0.0
    return (curve[-1] / curve[0]) - 1.0


def _calc_annualized_return(curve: List[float], trading_days: int = 252) -> float:
    """Annualized return from an equity curve."""
    if len(curve) < 2 or curve[0] <= 0:
        return 0.0
    tr = curve[-1] / curve[0]
    n_years = len(curve) / trading_days
    if n_years <= 0:
        return 0.0
    return float(tr ** (1.0 / n_years) - 1.0)


def _calc_sharpe(curve: List[float], risk_free_rate: float = 0.04, trading_days: int = 252) -> float:
    """Annualized Sharpe ratio."""
    arr = np.array(curve, dtype=float)
    if len(arr) < 3:
        return 0.0
    returns = np.diff(arr) / arr[:-1]
    returns = returns[~np.isnan(returns)]
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    excess = returns.mean() - (risk_free_rate / trading_days)
    return float(excess / np.std(returns, ddof=1) * np.sqrt(trading_days))


def _calc_max_drawdown(curve: List[float]) -> float:
    """Maximum drawdown."""
    if not curve:
        return 0.0
    arr = np.array(curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / np.where(peak != 0, peak, 1.0)
    return float(dd.min())


def _calc_beta(
    portfolio_returns: np.ndarray,
    benchmark_returns: np.ndarray,
) -> float:
    """Beta of portfolio vs benchmark."""
    if len(portfolio_returns) < 2 or len(benchmark_returns) < 2:
        return 0.0
    min_len = min(len(portfolio_returns), len(benchmark_returns))
    pr = portfolio_returns[:min_len]
    br = benchmark_returns[:min_len]
    cov = np.cov(pr, br)
    if cov.shape == (2, 2) and cov[1, 1] != 0:
        return float(cov[0, 1] / cov[1, 1])
    return 0.0


def build_benchmarks(
    sp500_prices: Optional[List[float]] = None,
    btc_prices: Optional[List[float]] = None,
    risk_free_rate: float = 0.04,
) -> Dict[str, BenchmarkResult]:
    """Build buy-and-hold benchmark results from price series.

    Args:
        sp500_prices: S&P 500 price series (oldest to newest).
        btc_prices: BTC price series (oldest to newest).
        risk_free_rate: Annual risk-free rate (default 4%).

    Returns:
        Dictionary of benchmark results.
    """
    benchmarks: Dict[str, BenchmarkResult] = {}

    if sp500_prices and len(sp500_prices) >= 2:
        # Build equity curve: start at 100, scale by price changes
        base = 100.0
        curve = [base]
        for i in range(1, len(sp500_prices)):
            curve.append(curve[-1] * (sp500_prices[i] / sp500_prices[i - 1]))
        result = BenchmarkResult(
            name="S&P 500 Buy & Hold",
            total_return=_calc_total_return(curve),
            annualized_return=_calc_annualized_return(curve),
            sharpe_ratio=_calc_sharpe(curve, risk_free_rate),
            max_drawdown=_calc_max_drawdown(curve),
            equity_curve=curve,
        )
        benchmarks["sp500"] = result

    if btc_prices and len(btc_prices) >= 2:
        base = 100.0
        curve = [base]
        for i in range(1, len(btc_prices)):
            curve.append(curve[-1] * (btc_prices[i] / btc_prices[i - 1]))
        result = BenchmarkResult(
            name="BTC Buy & Hold",
            total_return=_calc_total_return(curve),
            annualized_return=_calc_annualized_return(curve),
            sharpe_ratio=_calc_sharpe(curve, risk_free_rate),
            max_drawdown=_calc_max_drawdown(curve),
            equity_curve=curve,
        )
        benchmarks["btc"] = result

    return benchmarks


def compare_to_benchmarks(
    portfolio_equity_curve: List[float],
    sp500_prices: Optional[List[float]] = None,
    btc_prices: Optional[List[float]] = None,
    risk_free_rate: float = 0.04,
) -> BenchmarkComparison:
    """Compare portfolio performance to benchmarks.

    Calculates alpha and beta for each benchmark against the portfolio.

    Args:
        portfolio_equity_curve: Portfolio equity curve over time.
        sp500_prices: S&P 500 price series.
        btc_prices: BTC price series.
        risk_free_rate: Annual risk-free rate.

    Returns:
        BenchmarkComparison with all metrics.
    """
    benchmarks = build_benchmarks(sp500_prices, btc_prices, risk_free_rate)

    port_return = _calc_total_return(portfolio_equity_curve)
    port_sharpe = _calc_sharpe(portfolio_equity_curve, risk_free_rate)
    risk_free_daily = risk_free_rate / 252

    # Build portfolio daily returns
    arr = np.array(portfolio_equity_curve, dtype=float)
    port_returns = np.diff(arr) / arr[:-1]
    port_returns = port_returns[~np.isnan(port_returns)]

    alpha: Dict[str, float] = {}
    beta: Dict[str, float] = {}

    for key, bench in benchmarks.items():
        if len(bench.equity_curve) < 2:
            alpha[key] = 0.0
            beta[key] = 0.0
            continue
        barr = np.array(bench.equity_curve, dtype=float)
        bench_returns = np.diff(barr) / barr[:-1]
        bench_returns = bench_returns[~np.isnan(bench_returns)]

        b = _calc_beta(port_returns, bench_returns)
        beta[key] = b

        # Alpha = portfolio return - risk_free - beta * (benchmark return - risk_free)
        a = port_return - risk_free_rate - b * (bench.total_return - risk_free_rate)
        alpha[key] = a

    return BenchmarkComparison(
        portfolio_return=port_return,
        portfolio_sharpe=port_sharpe,
        benchmarks=benchmarks,
        alpha=alpha,
        beta=beta,
    )
