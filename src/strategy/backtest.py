"""CLI entry point for backtesting: python -m src.strategy.backtest

Usage:
    python -m src.strategy.backtest --strategy ma_crossover --symbol AAPL --start 2024-01-01
    python -m src.strategy.backtest --all --symbol AAPL --start 2024-01-01
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Optional

import pandas as pd


def _load_data_yfinance(symbol: str, start: str, end: Optional[str] = None) -> pd.DataFrame:
    """Fetch OHLCV data via yfinance and return as DataFrame with datetime index."""
    import yfinance as yf

    ticker = yf.Ticker(symbol)
    df = ticker.history(start=start, end=end, auto_adjust=True)
    if df.empty:
        print(f"No data returned for {symbol} between {start} and {end}")
        sys.exit(1)
    df.columns = [c.lower() for c in df.columns]
    if "adj close" in df.columns:
        df.drop(columns=["adj close"], inplace=True, errors="ignore")
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest trading strategies against historical data.",
    )
    parser.add_argument("--strategy", type=str, help="Strategy ID (e.g. ma_crossover)")
    parser.add_argument("--all", action="store_true", help="Backtest all registered strategies")
    parser.add_argument("--symbol", type=str, required=True, help="Ticker symbol (e.g. AAPL)")
    parser.add_argument("--start", type=str, required=True, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", type=str, default=None, help="End date YYYY-MM-DD (default: today)")
    parser.add_argument("--capital", type=float, default=100_000, help="Initial capital")
    parser.add_argument("--report", type=str, default="reports", help="Report output directory")
    args = parser.parse_args()

    from src.strategy.backtester import Backtester, CommissionConfig
    from src.strategy.equity_curve import generate_all_charts
    from src.strategy.library import get_strategy, list_strategies, load_strategies
    from src.strategy.reports import generate_html_report, generate_markdown_report

    load_strategies()
    data = _load_data_yfinance(args.symbol, args.start, args.end)
    print(f"Loaded {len(data)} bars for {args.symbol} ({args.start} → {args.end or 'today'})")

    backtester = Backtester(
        initial_capital=args.capital,
        commission=CommissionConfig(per_trade_fee=0.0),
    )

    strategy_ids: list[str] = []
    if args.all:
        strategy_ids = [s.id for s in list_strategies()]
        print(f"Running {len(strategy_ids)} strategies …")
    elif args.strategy:
        strategy_ids = [args.strategy]
    else:
        print("Specify --strategy or --all")
        sys.exit(1)

    results = []
    for sid in strategy_ids:
        strat = get_strategy(sid)
        if strat is None:
            print(f"Strategy '{sid}' not found, skipping")
            continue
        res = backtester.backtest(strat, data, symbol=args.symbol)
        print(f"  {sid}: return={res.total_return:.2%} sharpe={res.sharpe_ratio:.2f} trades={res.total_trades}")
        results.append(res)
        generate_all_charts(res, output_dir=args.report)

    if results:
        ranked = Backtester.rank_strategies(results)
        print("\n--- Ranked by Sharpe ---")
        for i, r in enumerate(ranked, 1):
            print(f"  {i}. {r.strategy_id}: Sharpe={r.sharpe_ratio:.2f}  Return={r.total_return:.2%}")

        generate_markdown_report(ranked, output_path=f"{args.report}/backtest_report.md")
        generate_html_report(ranked, output_path=f"{args.report}/backtest_report.html")
        print(f"\nReports saved to {args.report}/")


if __name__ == "__main__":
    main()
