"""CLI for the Learning Loop — python -m src.learning.status"""

import argparse
import json
import sys
from typing import Any, Dict

from src.learning.insights import InsightsEngine
from src.learning.tracker import Tracker
from src.learning.weights import WeightManager


def _load_demo_tracker() -> Tracker:
    """Create a tracker with demo data for CLI demonstration."""
    from datetime import datetime, timedelta
    from src.learning.tracker import TradeOutcome

    tracker = Tracker()
    now = datetime.utcnow()

    # Simulate trades for a few strategies
    strategies = ["ma_crossover", "rsi_mean_reversion", "macd_signal_cross"]
    for i, sid in enumerate(strategies):
        for j in range(20):
            days_ago = 30 - j
            entry = now - timedelta(days=days_ago)
            # Vary returns by strategy
            base_return = [0.01, 0.005, -0.002][i]
            ret = base_return + (0.02 if j % 3 == 0 else -0.01) * (1 if j % 2 == 0 else -1)
            outcome = TradeOutcome(
                trade_id=f"trade_{sid}_{j}",
                strategy_id=sid,
                symbol="AAPL",
                direction="LONG",
                entry_price=150.0,
                exit_price=150.0 * (1 + ret),
                quantity=10,
                entry_time=entry,
                exit_time=entry + timedelta(days=1),
                pnl=150.0 * ret * 10,
                return_pct=ret,
                regime="bull" if j < 10 else "sideways",
            )
            tracker.track_outcome(outcome)
            tracker.record_signal(sid)

    return tracker


def show_status() -> None:
    """Display current learning loop status."""
    tracker = _load_demo_tracker()
    wm = WeightManager()

    print("=" * 60)
    print("  TRADING INTELLIGENCE — Learning Loop Status")
    print("=" * 60)

    # Performance
    print("\n--- Strategy Performance (1M) ---")
    all_perf = tracker.get_all_performance("1m")
    for sid, perf in all_perf.items():
        print(
            f"  {sid:30s}  "
            f"Win: {perf.win_rate:5.1%}  "
            f"Sharpe: {perf.sharpe_ratio:+.2f}  "
            f"Trades: {perf.signals_taken:3d}"
        )

    # Weights
    print("\n--- Strategy Weights ---")
    weights = wm.recalculate_weights(all_perf)
    for sid, w in sorted(weights.items(), key=lambda x: -x[1]):
        bar = "#" * int(w * 100)
        print(f"  {sid:30s}  {w:5.1%}  {bar}")

    # Insights
    print("\n--- Insights ---")
    engine = InsightsEngine(tracker)
    report = engine.get_insights("1m")
    print(f"  System trend: {report.system_trend}")
    for insight in report.insights[:5]:
        print(f"  [{insight.category}] {insight.summary}")

    print("\n" + "=" * 60)


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Learning Loop Status — Trading Intelligence System"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output as JSON"
    )
    args = parser.parse_args()

    if args.json:
        tracker = _load_demo_tracker()
        wm = WeightManager()
        all_perf = tracker.get_all_performance("1m")
        weights = wm.recalculate_weights(all_perf)

        engine = InsightsEngine(tracker)
        report = engine.get_insights("1m")

        output: Dict[str, Any] = {
            "performance": {sid: p.to_dict() for sid, p in all_perf.items()},
            "weights": weights,
            "insights": {
                "best": report.best_strategies,
                "worst": report.worst_strategies,
                "trend": report.system_trend,
                "loss_patterns": report.loss_patterns,
            },
        }
        print(json.dumps(output, indent=2, default=str))
    else:
        show_status()


if __name__ == "__main__":
    main()
