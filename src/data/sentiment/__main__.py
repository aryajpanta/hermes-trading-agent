"""CLI entry point for the sentiment collector.

Usage:
    python -m src.data.sentiment --symbols AAPL,BTC --hours 24
    python -m src.data.sentiment --symbols AAPL --hours 48 --model vader
    python -m src.data.sentiment --symbols AAPL --history-only
"""

import argparse
import logging
import sys
from datetime import datetime, timezone

from src.data.sentiment.collector import SentimentCollector


def main() -> None:
    """Run the sentiment collector CLI."""
    parser = argparse.ArgumentParser(
        description="Financial news and sentiment collector"
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default="AAPL",
        help="Comma-separated symbols (default: AAPL)",
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Hours of history to query (default: 24)",
    )
    parser.add_argument(
        "--model",
        choices=["auto", "finbert", "vader"],
        default="auto",
        help="Sentiment model (default: auto)",
    )
    parser.add_argument(
        "--collect",
        choices=["all", "news", "social"],
        default="all",
        help="What to collect (default: all)",
    )
    parser.add_argument(
        "--history-only",
        action="store_true",
        help="Only show stored history, don't collect new data",
    )
    parser.add_argument(
        "--aggregate",
        action="store_true",
        help="Show aggregate sentiment summary",
    )
    parser.add_argument(
        "--db-path",
        default="data/sentiment.db",
        help="Path to sentiment database (default: data/sentiment.db)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("Error: No symbols provided")
        sys.exit(1)

    collector = SentimentCollector(
        storage_path=args.db_path,
        sentiment_model=args.model,
    )

    try:
        if args.history_only:
            _show_history(collector, symbols, args.hours)
        elif args.aggregate:
            _show_aggregate(collector, symbols, args.hours)
        else:
            _collect_and_show(collector, symbols, args)
    finally:
        collector.close()


def _collect_and_show(
    collector: SentimentCollector,
    symbols: list[str],
    args: argparse.Namespace,
) -> None:
    """Collect data and display results."""
    print(f"Collecting sentiment for: {', '.join(symbols)}")
    print(f"Model: {args.model}")
    print()

    # Show available models
    models = collector.get_available_models()
    print("Available models:")
    for name, available in models.items():
        status = "✓" if available else "✗"
        print(f"  {status} {name}")
    print()

    if args.collect in ("all", "news"):
        print("--- Collecting News ---")
        news_signals = collector.collect_news(symbols)
        print(f"  Fetched {len(news_signals)} news articles")
        for sig in news_signals[:5]:
            label = "📈" if sig.sentiment_score > 0.1 else "📉" if sig.sentiment_score < -0.1 else "➡️"
            print(
                f"  {label} [{sig.symbol}] {sig.headline[:60]}... "
                f"(score: {sig.sentiment_score:+.3f}, conf: {sig.confidence:.3f})"
            )
        print()

    if args.collect in ("all", "social"):
        print("--- Collecting Social ---")
        social_signals = collector.collect_social(symbols)
        print(f"  Fetched {len(social_signals)} social posts")
        for sig in social_signals[:5]:
            label = "📈" if sig.sentiment_score > 0.1 else "📉" if sig.sentiment_score < -0.1 else "➡️"
            print(
                f"  {label} [{sig.symbol}] {sig.headline[:60]}... "
                f"(score: {sig.sentiment_score:+.3f}, conf: {sig.confidence:.3f})"
            )
        print()

    # Show aggregates
    for symbol in symbols:
        agg = collector.get_aggregate_sentiment(symbol, args.hours)
        if agg.signal_count > 0:
            print(f"--- Aggregate: {symbol} ---")
            print(f"  Signals: {agg.signal_count}")
            print(f"  Mean Score: {agg.mean_score:+.4f} ({agg.sentiment_label})")
            print(f"  Confidence: {agg.confidence:.4f}")
            print(f"  Bullish/Bearish/Neutral: {agg.bullish_count}/{agg.bearish_count}/{agg.neutral_count}")
            print(f"  Sources: {agg.sources_breakdown}")
            print()


def _show_history(collector: SentimentCollector, symbols: list[str], hours: int) -> None:
    """Show sentiment history for symbols."""
    for symbol in symbols:
        print(f"\n--- Sentiment History: {symbol} (last {hours}h) ---")
        df = collector.get_sentiment_history(symbol, hours)
        if df.empty:
            print("  No data found")
        else:
            print(df.to_string(index=False))
            print(f"\n  Total signals: {len(df)}")


def _show_aggregate(collector: SentimentCollector, symbols: list[str], hours: int) -> None:
    """Show aggregate sentiment for symbols."""
    print(f"\n{'='*60}")
    print(f"  AGGREGATE SENTIMENT SUMMARY (last {hours}h)")
    print(f"{'='*60}")

    for symbol in symbols:
        agg = collector.get_aggregate_sentiment(symbol, hours)
        print(f"\n  {symbol}:")
        if agg.signal_count == 0:
            print("    No signals found")
            continue
        print(f"    Score:    {agg.mean_score:+.4f} ({agg.sentiment_label})")
        print(f"    Conf:     {agg.confidence:.4f}")
        print(f"    Signals:  {agg.signal_count}")
        print(f"    Bullish:  {agg.bullish_count}")
        print(f"    Bearish:  {agg.bearish_count}")
        print(f"    Neutral:  {agg.neutral_count}")
        print(f"    Engage:   {agg.engagement_total}")
        if agg.sources_breakdown:
            print(f"    Sources:  {agg.sources_breakdown}")

    print(f"\n{'='*60}")


if __name__ == "__main__":
    main()
