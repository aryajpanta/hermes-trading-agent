#!/usr/bin/env python3
"""Migrate open positions from HTA (Node/Railway) to the unified Python system.

Run ONCE before the Node service is decommissioned. Reads the HTA /api/portfolio
endpoint, writes the positions to data/paper_portfolio.json in TI's format, and
saves a backup to data/legacy_positions.json.

Usage:
    python scripts/migrate_hta_positions.py
    python scripts/migrate_hta_positions.py --dry-run
    python scripts/migrate_hta_positions.py --url https://custom.url
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

DEFAULT_URL = "https://hermes-trading-agent-production-890e.up.railway.app"
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"


def fetch_hta_portfolio(url: str) -> dict:
    """Fetch current portfolio state from the HTA Node service."""
    r = requests.get(f"{url}/api/portfolio", timeout=15)
    r.raise_for_status()
    return r.json()


def fetch_current_prices(url: str, symbols: List[str]) -> Dict[str, Optional[float]]:
    """Fetch current prices for the open position symbols."""
    r = requests.get(
        f"{url}/api/prices",
        params={"symbols": ",".join(symbols)},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    out = {}
    for sym, info in data.items():
        price = info.get("price")
        out[sym] = float(price) if price is not None else None
    return out


def convert_positions(hta_positions: List[dict], current_prices: Dict[str, Optional[float]]) -> List[dict]:
    """Convert HTA position format to TI paper portfolio format."""
    converted = []
    for p in hta_positions:
        if p.get("status") != "open":
            continue
        sym = p["symbol"]
        entry = float(p["entryPrice"])
        qty = float(p["quantity"])
        cur = current_prices.get(sym) or entry
        converted.append(
            {
                "symbol": sym,
                "qty": f"{qty:.10f}",
                "avg_price": f"{entry:.10f}",
                "current_price": f"{cur:.10f}",
                "unrealized_pl": f"{(cur - entry) * qty:.4f}",
                "stop_loss": p.get("stopLoss"),
                "take_profit": p.get("takeProfit"),
                "side": p.get("side", "long"),
                "reason": p.get("reason", ""),
                "opened_at": p.get("openedAt"),
                "legacy_id": p.get("id"),
            }
        )
    return converted


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL, help="HTA base URL")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing")
    args = parser.parse_args()

    print(f"Fetching portfolio from {args.url} ...")
    hta = fetch_hta_portfolio(args.url)
    open_positions = [p for p in hta.get("positions", []) if p.get("status") == "open"]
    print(f"  Found {len(open_positions)} open positions, {hta.get('tradeCount', 0)} total trades")
    print(f"  Cash: ${hta.get('balances', {}).get('USD', 0):,.2f}")
    print(f"  Total value: ${hta.get('totalValue', 0):,.2f}")

    symbols = [p["symbol"] for p in open_positions]
    print(f"\nFetching current prices for {symbols} ...")
    current_prices = fetch_current_prices(args.url, symbols)
    for sym, price in current_prices.items():
        if price is not None:
            print(f"  {sym}: ${price:,.4f}")
        else:
            print(f"  {sym}: unavailable (will use entry price)")

    converted = convert_positions(open_positions, current_prices)
    cash = float(hta.get("balances", {}).get("USD", 0))

    paper_portfolio = {
        "cash": cash,
        "positions": converted,
        "starting_balance": 100000.0,
        "legacy_source": "hermes-trading-agent",
        "legacy_url": args.url,
        "migrated_at": datetime.utcnow().isoformat() + "Z",
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }

    legacy_snapshot = {
        "source": "hermes-trading-agent (HTA)",
        "snapshot_at": datetime.utcnow().isoformat() + "Z",
        "cash_usd": cash,
        "total_value": hta.get("totalValue"),
        "peak_balance": hta.get("peakBalance"),
        "trade_count": hta.get("tradeCount"),
        "winning_trades": hta.get("winningTrades"),
        "losing_trades": hta.get("losingTrades"),
        "raw": hta,
        "current_prices_at_migration": current_prices,
    }

    if args.dry_run:
        print("\n[DRY RUN] Would write:")
        print(json.dumps(paper_portfolio, indent=2))
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    backup_path = DATA_DIR / "legacy_positions.json"
    with open(backup_path, "w") as f:
        json.dump(legacy_snapshot, f, indent=2, default=str)
    print(f"\n✅ Wrote backup: {backup_path}")

    portfolio_path = DATA_DIR / "paper_portfolio.json"
    with open(portfolio_path, "w") as f:
        json.dump(paper_portfolio, f, indent=2, default=str)
    print(f"✅ Wrote portfolio: {portfolio_path}")

    print(f"\nMigration complete: {len(converted)} positions, ${cash:,.2f} cash")
    print("Next step: deploy the unified Python service, then stop the Node service.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
