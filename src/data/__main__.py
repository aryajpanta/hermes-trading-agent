"""CLI entry point for the Market Data Collection System.

Usage:
    python -m src.data.cli --symbols AAPL,GOOGL --period 1y
"""

from src.data.cli import main

if __name__ == "__main__":
    main()
