#!/usr/bin/env python3
"""
Automated Trading Script for Trading Intelligence System.

Runs on a schedule to:
1. Collect latest market data
2. Evaluate all strategies
3. Generate trade recommendations
4. Execute paper trades (auto-approve in paper mode)
5. Update portfolio positions
6. Generate daily summary
"""

import sys
import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data.collector import MarketDataCollector
import src.strategy.library as library
from src.decision.engine import DecisionEngine
from src.execution.paper import PaperTrader

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Config
WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "QQQ", "SPY"]
CRYPTO = ["BTC", "ETH"]
DB_PATH = "data/market.db"
PORTFOLIO_FILE = "data/paper_portfolio.json"
SUMMARY_FILE = "data/daily_summary.json"


def collect_data(collector: MarketDataCollector) -> dict:
    """Collect latest market data for watchlist."""
    logger.info("Collecting market data...")
    results = {}
    all_symbols = WATCHLIST + CRYPTO
    for symbol in all_symbols:
        try:
            result = collector.collect(symbol, period="5d", interval="1d")
            results[symbol] = {
                "success": result.success,
                "records": result.records_collected,
                "source": result.source.value if result.source else None
            }
            status = "✅" if result.success else "❌"
            logger.info(f"  {symbol}: {status} ({result.records_collected} records)")
        except Exception as e:
            logger.error(f"  {symbol}: Error - {e}")
            results[symbol] = {"success": False, "error": str(e)}
    return results


def evaluate_strategies(collector: MarketDataCollector) -> Dict[str, list]:
    """Evaluate all strategies on watchlist symbols."""
    logger.info("Evaluating strategies...")
    library.load_strategies()
    all_strategies = library.list_strategies()
    strategy_ids = [s.id for s in all_strategies]
    logger.info(f"  Loaded {len(strategy_ids)} strategies")
    
    signals = {}
    for symbol in WATCHLIST[:5]:  # Top 5 for speed
        try:
            history = collector.get_history(symbol, days=100)
            if history.empty:
                continue
            symbol_signals = []
            for strat_id in strategy_ids:
                try:
                    signal = library.evaluate(strat_id, history, symbol)
                    symbol_signals.append({
                        "strategy_id": strat_id,
                        "direction": signal.direction,
                        "confidence": signal.confidence,
                        "reasoning": signal.reasoning
                    })
                except Exception as e:
                    logger.debug(f"    {strat_id}: {e}")
            signals[symbol] = symbol_signals
            active = sum(1 for s in symbol_signals if abs(s.get("direction", 0)) > 0.3)
            logger.info(f"  {symbol}: {active} active signals out of {len(symbol_signals)}")
        except Exception as e:
            logger.error(f"  {symbol}: Strategy evaluation error - {e}")
    return signals


def generate_recommendations(engine: DecisionEngine, collector: MarketDataCollector) -> List[Dict[str, Any]]:
    """Generate trade recommendations for watchlist symbols."""
    logger.info("Generating recommendations...")
    recommendations = []
    for symbol in WATCHLIST[:5]:  # Top 5 for speed
        try:
            data = collector.get_history(symbol, days=100)
            if data.empty:
                continue
            result = engine.analyze(symbol, data)
            if result and result.recommendation and result.recommendation.direction.value != "HOLD":
                rec = result.recommendation.to_dict()
                recommendations.append(rec)
                logger.info(f"  {symbol}: {rec['direction']} (confidence: {rec['confidence']:.2f})")
        except Exception as e:
            logger.error(f"  {symbol}: Recommendation error - {e}")
    return recommendations


def execute_trades(trader: PaperTrader, recommendations: List[Dict[str, Any]]) -> list:
    """Execute paper trades for recommendations."""
    logger.info("Executing paper trades...")
    executed = []
    for rec in recommendations:
        try:
            result = trader.execute_signal(rec)
            if result:
                executed.append(rec)
                logger.info(f"  ✅ {rec['symbol']}: {rec['direction']} executed")
        except Exception as e:
            logger.error(f"  ❌ {rec['symbol']}: Execution error - {e}")
    return executed


def generate_summary(data_results: dict, signals: dict, recommendations: list,
                     executed: list, trader: PaperTrader) -> dict:
    """Generate daily summary."""
    portfolio = trader.get_portfolio()

    summary = {
        "timestamp": datetime.now().isoformat(),
        "data_collection": {
            "total_symbols": len(data_results),
            "successful": sum(1 for r in data_results.values() if r.get("success")),
            "failed": sum(1 for r in data_results.values() if not r.get("success"))
        },
        "signals": {
            "total_symbols": len(signals),
            "active_signals": sum(
                sum(1 for s in strat_signals if abs(s.get("direction", 0)) > 0.3)
                for strat_signals in signals.values()
            )
        },
        "recommendations": {
            "total": len(recommendations),
            "buy": sum(1 for r in recommendations if r.get("direction") == "BUY"),
            "sell": sum(1 for r in recommendations if r.get("direction") == "SELL")
        },
        "trades_executed": len(executed),
        "portfolio": {
            "total_value": portfolio.get("total_value", 0),
            "cash": portfolio.get("cash", 0),
            "daily_pnl": portfolio.get("daily_pnl", 0),
            "total_pnl": portfolio.get("total_pnl", 0),
            "positions": portfolio.get("positions_count", 0)
        }
    }

    # Save summary
    os.makedirs("data", exist_ok=True)
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    return summary


def format_summary_message(summary: dict) -> str:
    """Format summary for Discord message."""
    msg = f"## 📊 Trading Intelligence — Daily Summary\n"
    msg += f"**{datetime.now().strftime('%Y-%m-%d %H:%M')}**\n\n"

    # Data
    d = summary["data_collection"]
    msg += f"### Data Collection\n"
    msg += f"• {d['successful']}/{d['total_symbols']} symbols updated\n\n"

    # Signals
    s = summary["signals"]
    msg += f"### Strategy Signals\n"
    msg += f"• {s['active_signals']} active signals across {s['total_symbols']} symbols\n\n"

    # Recommendations
    r = summary["recommendations"]
    msg += f"### Recommendations\n"
    msg += f"• {r['total']} total: {r['buy']} BUY, {r['sell']} SELL\n\n"

    # Trades
    msg += f"### Trades Executed\n"
    msg += f"• {summary['trades_executed']} paper trades\n\n"

    # Portfolio
    p = summary["portfolio"]
    msg += f"### Portfolio\n"
    msg += f"• Value: ${p['total_value']:,.2f}\n"
    msg += f"• Cash: ${p['cash']:,.2f}\n"
    msg += f"• Daily P&L: ${p['daily_pnl']:+,.2f}\n"
    msg += f"• Total P&L: ${p['total_pnl']:+,.2f}\n"
    msg += f"• Positions: {p['positions']}\n"

    return msg


def main():
    """Main trading loop."""
    logger.info("=" * 60)
    logger.info("Trading Intelligence - Automated Run")
    logger.info("=" * 60)

    try:
        # Initialize components
        collector = MarketDataCollector(storage_path=DB_PATH)
        engine = DecisionEngine()
        trader = PaperTrader()

        # Load existing portfolio if available
        if os.path.exists(PORTFOLIO_FILE):
            try:
                with open(PORTFOLIO_FILE, "r") as f:
                    portfolio_data = json.load(f)
                # Restore portfolio state
                trader.portfolio.cash = portfolio_data.get("cash", 100000)
                logger.info(f"Loaded portfolio: ${trader.portfolio.cash:,.2f} cash")
            except Exception as e:
                logger.warning(f"Could not load portfolio: {e}")

        # 1. Collect data
        data_results = collect_data(collector)

        # 2. Evaluate strategies
        signals = evaluate_strategies(collector)

        # 3. Generate recommendations
        recommendations = generate_recommendations(engine, collector)

        # 4. Execute trades
        executed = execute_trades(trader, recommendations)

        # 5. Update portfolio
        # Get current prices for portfolio update
        market_prices = {}
        for symbol in ["QQQ", "SPY", "AAPL", "MSFT", "GOOGL"]:
            try:
                latest = collector.get_latest(symbol)
                if latest:
                    market_prices[symbol] = latest.close
            except Exception:
                pass
        if market_prices:
            trader.update_positions(market_prices)

        # 6. Save portfolio
        os.makedirs("data", exist_ok=True)
        portfolio_data = {
            "cash": trader.portfolio.cash,
            "positions": [
                {
                    "symbol": p.symbol,
                    "qty": str(p.quantity),
                    "avg_price": str(p.entry_price),
                    "current_price": str(p.current_price) if hasattr(p, 'current_price') else str(p.entry_price),
                    "unrealized_pl": str(p.unrealized_pnl) if hasattr(p, 'unrealized_pnl') else "0"
                }
                for p in trader.portfolio.positions
            ],
            "updated_at": datetime.now().isoformat()
        }
        with open(PORTFOLIO_FILE, "w") as f:
            json.dump(portfolio_data, f, indent=2)

        # 7. Generate summary
        summary = generate_summary(data_results, signals, recommendations, executed, trader)

        # 8. Print summary
        print("\n" + format_summary_message(summary))

        logger.info("Run complete!")
        return summary

    except Exception as e:
        logger.error(f"Trading run failed: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        try:
            collector.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
