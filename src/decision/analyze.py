"""CLI entry point for the Decision Engine.

Usage:
    python -m src.decision.analyze --symbol AAPL
    python -m src.decision.analyze --symbol AAPL --portfolio-value 50000
    python -m src.decision.analyze --symbol AAPL --explain
    python -m src.decision.analyze --symbol AAPL --simulate 0.05
"""

import argparse
import logging
import sys
from typing import List, Optional

import numpy as np
import pandas as pd

from src.decision.engine import DecisionEngine
from src.decision.logging import format_recommendation, get_decision_logs


def generate_synthetic_data(n_bars: int = 250, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for testing/demonstration.

    Args:
        n_bars: Number of bars to generate.
        seed: Random seed for reproducibility.

    Returns:
        OHLCV DataFrame.
    """
    rng = np.random.RandomState(seed)
    dates = pd.date_range("2023-01-01", periods=n_bars, freq="B")
    returns = rng.normal(0.0005, 0.02, n_bars)
    close = 150.0 * np.cumprod(1 + returns)

    high = close * (1 + rng.uniform(0, 0.02, n_bars))
    low = close * (1 - rng.uniform(0, 0.02, n_bars))
    open_ = close * (1 + rng.normal(0, 0.005, n_bars))
    volume = rng.randint(100_000, 5_000_000, n_bars).astype(float)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


def main(argv: Optional[List[str]] = None) -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Decision Engine — generate trade recommendations"
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="Ticker symbol to analyze (e.g., AAPL, TSLA)",
    )
    parser.add_argument(
        "--portfolio-value",
        type=float,
        default=100000.0,
        help="Total portfolio value for position sizing (default: 100000)",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.6,
        help="Minimum confidence threshold (default: 0.6)",
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=0.05,
        help="Maximum position size as fraction (default: 0.05 = 5%%)",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="Show detailed explanation of the recommendation",
    )
    parser.add_argument(
        "--simulate",
        type=float,
        default=None,
        help="Simulate a price change (e.g., 0.05 for +5%%, -0.10 for -10%%)",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args(argv)

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Configure risk
    from src.decision.models import RiskConfig

    risk_config = RiskConfig(
        min_confidence=args.min_confidence,
        max_position_pct=args.max_position,
    )

    # Generate data (in production, this would fetch real market data)
    print(f"Generating synthetic data for {args.symbol}...")
    data = generate_synthetic_data(n_bars=250)

    # Run analysis
    engine = DecisionEngine(risk_config=risk_config)
    result = engine.analyze(
        symbol=args.symbol,
        data=data,
        portfolio_value=args.portfolio_value,
    )

    # Output results
    if args.explain:
        print(engine.explain(result))
    elif result.recommendation is not None:
        print(format_recommendation(result.recommendation))
    else:
        print(f"\n{'=' * 60}")
        print(f"  {args.symbol}: HOLD (no trade)")
        print(f"{'=' * 60}")
        print(f"  Aggregated Direction: {result.aggregated.direction if result.aggregated else 0:.3f}")
        print(f"  Aggregate Confidence: {result.aggregated.confidence if result.aggregated else 0:.3f}")
        print(f"  Strategies Evaluated: {len(result.signals)}")
        print(f"  Reasoning: {result.reasoning}")
        print(f"{'=' * 60}")

    # Simulate if requested
    if args.simulate is not None:
        print(f"\n--- Simulation: {args.simulate:+.1%} price move ---")
        sim = engine.simulate(result, args.simulate)
        print(f"  Action: {sim['action']}")
        print(f"  P&L: {sim['simulated_pnl_pct']:+.2%}")
        print(f"  Outcome: {sim['explanation']}")

    # Show recent logs
    logs = engine.get_logs(symbol=args.symbol)
    if logs:
        print(f"\nDecision log: {len(logs)} entries for {args.symbol}")


if __name__ == "__main__":
    main()
