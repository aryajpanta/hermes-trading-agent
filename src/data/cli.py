"""CLI entry point for the Market Data Collection System.

Usage:
    python -m src.data.cli --symbols AAPL,GOOGL --period 1y
    python -m src.data.cli --symbols BTC,ETH --source coingecko
    python -m src.data.cli --list-symbols
    python -m src.data.cli --stats
"""

import logging
import sys
from typing import Optional

import click

from src.data.collector import MarketDataCollector
from src.data.models import (
    DEFAULT_COMMODITIES,
    DEFAULT_CRYPTO,
    DEFAULT_FOREX,
    DEFAULT_STOCKS,
    DataSource,
)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


@click.command()
@click.option(
    "--symbols",
    "-s",
    type=str,
    default=None,
    help="Comma-separated list of symbols to collect (e.g., AAPL,GOOGL,BTC)",
)
@click.option(
    "--period",
    "-p",
    type=str,
    default="1y",
    help="Time period to fetch (e.g., 1y, 6mo, 30d, 1w)",
)
@click.option(
    "--interval",
    "-i",
    type=str,
    default="1d",
    help="Data interval (e.g., 1d, 1h, 5m)",
)
@click.option(
    "--source",
    type=click.Choice(["yahoo", "coingecko", "alpha_vantage"], case_sensitive=False),
    default=None,
    help="Preferred data source",
)
@click.option(
    "--db-path",
    type=str,
    default="data/market.db",
    help="Path to SQLite database",
)
@click.option(
    "--list-symbols",
    is_flag=True,
    help="List all tracked symbols",
)
@click.option(
    "--list-defaults",
    is_flag=True,
    help="List all default supported symbols",
)
@click.option(
    "--stats",
    is_flag=True,
    help="Show collection statistics",
)
@click.option(
    "--init-defaults",
    is_flag=True,
    help="Initialize database with default symbols",
)
@click.option(
    "--alphavantage-key",
    type=str,
    default="",
    envvar="ALPHA_VANTAGE_API_KEY",
    help="Alpha Vantage API key",
)
@click.option(
    "--coingecko-key",
    type=str,
    default="",
    envvar="COINGECKO_API_KEY",
    help="CoinGecko API key (optional)",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
@click.option(
    "--batch-size",
    type=int,
    default=5,
    help="Number of symbols to process before pausing",
)
def main(
    symbols: Optional[str],
    period: str,
    interval: str,
    source: Optional[str],
    db_path: str,
    list_symbols: bool,
    list_defaults: bool,
    stats: bool,
    init_defaults: bool,
    alphavantage_key: str,
    coingecko_key: str,
    verbose: bool,
    batch_size: int,
) -> None:
    """Market Data Collection CLI for Trading Intelligence System."""
    setup_logging(verbose)
    logger = logging.getLogger(__name__)

    # Parse source
    data_source: Optional[DataSource] = None
    if source:
        data_source = DataSource(source.lower())

    # Initialize collector
    collector = MarketDataCollector(
        storage_path=db_path,
        alphavantage_api_key=alphavantage_key,
        coingecko_api_key=coingecko_key,
    )

    try:
        # List symbols mode
        if list_symbols:
            symbols_list = collector.list_symbols(active_only=False)
            if not symbols_list:
                click.echo("No symbols tracked. Use --init-defaults to add default symbols.")
                return

            click.echo(f"\n{'Symbol':<12} {'Type':<10} {'Source':<15} {'Active':<8}")
            click.echo("-" * 45)
            for sym in symbols_list:
                click.echo(
                    f"{sym.symbol:<12} {sym.asset_type:<10} {sym.source.value:<15} "
                    f"{'Yes' if sym.is_active else 'No':<8}"
                )
            click.echo(f"\nTotal: {len(symbols_list)} symbols")
            return

        # List defaults mode
        if list_defaults:
            click.echo("\n=== Default Supported Symbols ===\n")

            click.echo("Stocks (Top 20 S&P 500):")
            for s in DEFAULT_STOCKS:
                click.echo(f"  {s}")

            click.echo("\nCrypto:")
            for s in DEFAULT_CRYPTO:
                click.echo(f"  {s}")

            click.echo("\nForex:")
            for s in DEFAULT_FOREX:
                click.echo(f"  {s}")

            click.echo("\nCommodities:")
            for s in DEFAULT_COMMODITIES:
                click.echo(f"  {s}")

            total = len(DEFAULT_STOCKS) + len(DEFAULT_CRYPTO) + len(DEFAULT_FOREX) + len(DEFAULT_COMMODITIES)
            click.echo(f"\nTotal: {total} default symbols")
            return

        # Initialize defaults mode
        if init_defaults:
            count = collector.initialize_default_symbols()
            click.echo(f"Initialized {count} new symbols in database")
            return

        # Stats mode
        if stats:
            click.echo("\n=== Collection Statistics ===\n")
            overall = collector.get_collection_stats()
            click.echo(f"Total records: {overall['total']}")
            for source_name, count in overall.items():
                if source_name not in ("total", "earliest", "latest"):
                    click.echo(f"  {source_name}: {count} records")
            click.echo("")

            # Per-symbol stats
            symbols_list = collector.list_symbols()
            if symbols_list:
                click.echo(f"\n{'Symbol':<12} {'Records':<10} {'Source':<15}")
                click.echo("-" * 37)
                for sym in symbols_list[:20]:  # Show top 20
                    sym_stats = collector.get_collection_stats(sym.symbol)
                    click.echo(
                        f"{sym.symbol:<12} {sym_stats['total']:<10} "
                        f"{sym.source.value:<15}"
                    )
            return

        # Collect mode
        if not symbols:
            click.echo("Error: --symbols is required for collection. Use --help for usage.")
            sys.exit(1)

        symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]

        if not symbol_list:
            click.echo("Error: No valid symbols provided")
            sys.exit(1)

        click.echo(f"\nCollecting data for: {', '.join(symbol_list)}")
        click.echo(f"Period: {period}, Interval: {interval}")
        if data_source:
            click.echo(f"Source: {data_source.value}")
        click.echo("")

        # Process in batches
        for i in range(0, len(symbol_list), batch_size):
            batch = symbol_list[i : i + batch_size]
            result = collector.collect_batch(
                symbols=batch,
                sources=[data_source] if data_source else None,
                period=period,
                interval=interval,
            )

            for r in result.results:
                status = "✓" if r.success else "✗"
                click.echo(
                    f"  {status} {r.symbol}: {r.records_collected} records "
                    f"({r.source.value}) [{r.duration_seconds:.1f}s]"
                )
                if not r.success and r.error_message:
                    click.echo(f"    Error: {r.error_message}")

            # Progress summary
            click.echo(
                f"\nBatch {i // batch_size + 1}: "
                f"{result.successful_symbols}/{len(batch)} successful, "
                f"{result.total_records} total records"
            )

            # Pause between batches
            if i + batch_size < len(symbol_list):
                import time
                click.echo("Pausing between batches...")
                time.sleep(1)

        # Final summary
        click.echo("\nCollection complete!")

    except KeyboardInterrupt:
        click.echo("\n\nCollection interrupted by user")
        sys.exit(1)
    except Exception as e:
        click.echo(f"\nError: {e}")
        logger.exception("Collection failed")
        sys.exit(1)
    finally:
        collector.close()


if __name__ == "__main__":
    main()
