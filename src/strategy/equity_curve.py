"""Equity-curve and drawdown chart generation.

Produces PNG images of equity curves and drawdown charts for backtest results.
"""

from pathlib import Path
from typing import List, Optional, Tuple

import matplotlib
matplotlib.use("Agg")  # non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
import pandas as pd

from src.strategy.backtester import BacktestResult


def plot_equity_curve(
    result: BacktestResult,
    output_path: Optional[str] = None,
    title: Optional[str] = None,
    figsize: Tuple[int, int] = (12, 6),
) -> str:
    """Save equity curve as a PNG and return the file path."""
    eq = result.equity_curve
    if eq.empty:
        return ""

    fig, ax = plt.subplots(figsize=figsize)
    ax.plot(eq.index, eq.values, linewidth=1.2, color="#2196F3")
    ax.fill_between(eq.index, eq.values, alpha=0.15, color="#2196F3")
    ax.axhline(y=eq.values[0], color="gray", linestyle="--", linewidth=0.8, alpha=0.5)

    ax.set_title(
        title or f"Equity Curve — {result.strategy_id} on {result.symbol}",
        fontsize=14, fontweight="bold",
    )
    ax.set_ylabel("Portfolio Value ($)")
    ax.set_xlabel("Date")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    fig.autofmt_xdate()

    # Stats box
    stats_text = (
        f"Return: {result.total_return:.2%}\n"
        f"Sharpe: {result.sharpe_ratio:.2f}\n"
        f"Max DD: {result.max_drawdown:.2%}\n"
        f"Trades: {result.total_trades}"
    )
    ax.text(
        0.02, 0.97, stats_text,
        transform=ax.transAxes, fontsize=9,
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.4", facecolor="wheat", alpha=0.85),
    )

    plt.tight_layout()

    if output_path is None:
        output_path = f"reports/{result.strategy_id}_{result.symbol}_equity.png"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def plot_drawdown(
    result: BacktestResult,
    output_path: Optional[str] = None,
    figsize: Tuple[int, int] = (12, 3),
) -> str:
    """Save a drawdown chart as PNG and return the file path."""
    eq = result.equity_curve
    if eq.empty:
        return ""

    peak = eq.cummax()
    dd = (eq - peak) / peak

    fig, ax = plt.subplots(figsize=figsize)
    ax.fill_between(dd.index, dd.values, 0, color="#F44336", alpha=0.45)
    ax.plot(dd.index, dd.values, linewidth=0.8, color="#B71C1C")
    ax.set_title(
        f"Drawdown — {result.strategy_id} on {result.symbol}",
        fontsize=12, fontweight="bold",
    )
    ax.set_ylabel("Drawdown")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    fig.autofmt_xdate()
    plt.tight_layout()

    if output_path is None:
        output_path = f"reports/{result.strategy_id}_{result.symbol}_drawdown.png"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def plot_monthly_heatmap(
    result: BacktestResult,
    output_path: Optional[str] = None,
    figsize: Tuple[int, int] = (10, 4),
) -> str:
    """Save a monthly-return heatmap as PNG."""
    eq = result.equity_curve
    if eq.empty:
        return ""

    monthly = eq.resample("ME").last().pct_change().dropna()
    if monthly.empty:
        return ""

    df = pd.DataFrame({
        "year": monthly.index.year,
        "month": monthly.index.month,
        "return": monthly.values,
    })
    pivot = df.pivot_table(index="year", columns="month", values="return", aggfunc="mean")
    pivot.columns = [f"{m}" for m in pivot.columns]

    fig, ax = plt.subplots(figsize=figsize)
    im = ax.imshow(pivot.values, cmap="RdYlGn", aspect="auto", vmin=-0.1, vmax=0.1)
    ax.set_xticks(range(len(pivot.columns)))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(range(len(pivot.index)))
    ax.set_yticklabels(pivot.index)
    ax.set_title(
        f"Monthly Returns — {result.strategy_id}",
        fontsize=12, fontweight="bold",
    )
    fig.colorbar(im, ax=ax, label="Monthly Return")
    plt.tight_layout()

    if output_path is None:
        output_path = f"reports/{result.strategy_id}_monthly_heatmap.png"
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
    return output_path


def generate_all_charts(
    result: BacktestResult,
    output_dir: str = "reports",
) -> List[str]:
    """Generate equity curve, drawdown, and heatmap; return file paths."""
    prefix = f"{output_dir}/{result.strategy_id}_{result.symbol}"
    paths: List[str] = []
    p = plot_equity_curve(result, output_path=f"{prefix}_equity.png")
    if p:
        paths.append(p)
    p = plot_drawdown(result, output_path=f"{prefix}_drawdown.png")
    if p:
        paths.append(p)
    p = plot_monthly_heatmap(result, output_path=f"{prefix}_monthly_heatmap.png")
    if p:
        paths.append(p)
    return paths
