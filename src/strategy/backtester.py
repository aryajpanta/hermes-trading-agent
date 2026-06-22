"""Backtesting engine — runs strategies against historical OHLCV data.

Simulates bar-by-bar trading, tracks positions, applies commission/slippage
models, and produces BacktestResult objects with full trade logs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.signals import Signal


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    """A single completed round-trip trade."""
    entry_date: datetime
    exit_date: datetime
    entry_price: float
    exit_price: float
    direction: float          # +1.0 long, -1.0 short
    shares: float
    pnl: float
    pnl_pct: float
    holding_period_days: int
    commission: float


@dataclass
class CommissionConfig:
    """Commission and spread model for realistic backtesting."""
    per_trade_fee: float = 0.0
    per_share_fee: float = 0.0
    spread_pct: float = 0.001  # 0.1% spread assumption


@dataclass
class BacktestResult:
    """Full result of a single strategy backtest."""
    strategy_id: str
    symbol: str
    period: str               # e.g. "2024-01-01/2024-12-31"
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_holding_period: float
    trade_log: List[Trade]
    equity_curve: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    def summary_dict(self) -> Dict[str, Any]:
        """Return a flat dictionary of key metrics."""
        return {
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "period": self.period,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "sortino_ratio": self.sortino_ratio,
            "max_drawdown": self.max_drawdown,
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "total_trades": self.total_trades,
            "avg_holding_period": self.avg_holding_period,
        }


# ---------------------------------------------------------------------------
# Backtester engine
# ---------------------------------------------------------------------------

class Backtester:
    """Runs a single strategy (or batch) against historical data.

    Parameters
    ----------
    initial_capital : float
        Starting portfolio value.
    position_size_pct : float
        Fraction of equity used per trade (0.0–1.0).
    commission : CommissionConfig
        Fee model applied to every fill.
    signal_threshold : float
        Absolute signal direction required to trigger a trade.
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        position_size_pct: float = 0.95,
        commission: Optional[CommissionConfig] = None,
        signal_threshold: float = 0.3,
    ) -> None:
        self.initial_capital = initial_capital
        self.position_size_pct = position_size_pct
        self.commission = commission or CommissionConfig()
        self.signal_threshold = signal_threshold

    # ------------------------------------------------------------------
    # Single-strategy backtest
    # ------------------------------------------------------------------

    def backtest(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        symbol: str = "",
    ) -> BacktestResult:
        """Run *strategy* bar-by-bar over *data* and return a BacktestResult.

        The engine slices the DataFrame up to each bar, calls
        ``strategy.evaluate()`` and acts on the resulting Signal.
        """
        if not strategy.validate_data(data):
            return self._empty_result(strategy.config.id, symbol, data)

        min_bars = strategy.minimum_data_points()
        equity = self.initial_capital
        position: float = 0.0          # shares held
        entry_price: float = 0.0
        entry_date: Optional[datetime] = None
        direction: float = 0.0

        equity_values: List[Tuple[datetime, float]] = []
        trades: List[Trade] = []

        close = data["close"]
        idx = data.index

        for i in range(min_bars, len(data)):
            current_date = idx[i] if isinstance(idx[i], datetime) else datetime.fromtimestamp(idx[i].timestamp()) if hasattr(idx[i], 'timestamp') else datetime.now()
            current_price = float(close.iloc[i])

            # --- Evaluate strategy on history up to now ---
            slice_df = data.iloc[: i + 1].copy()
            signal: Signal = strategy.evaluate(slice_df)

            # --- Position management ---
            if position == 0:
                # No position — check for entry
                if signal.direction >= self.signal_threshold:
                    # BUY
                    entry_price = self._apply_buy_price(current_price)
                    comm = self._trade_commission(equity, entry_price)
                    equity -= comm
                    shares = (equity * self.position_size_pct) / entry_price
                    position = shares
                    direction = 1.0
                    entry_date = current_date
                elif signal.direction <= -self.signal_threshold:
                    # SHORT (sell)
                    entry_price = self._apply_sell_price(current_price)
                    comm = self._trade_commission(equity, entry_price)
                    equity -= comm
                    shares = (equity * self.position_size_pct) / entry_price
                    position = -shares  # negative = short
                    direction = -1.0
                    entry_price = current_price
                    entry_date = current_date
            else:
                # Have a position — check for exit (reverse signal)
                exit_signal = (
                    (direction > 0 and signal.direction <= -self.signal_threshold)
                    or (direction < 0 and signal.direction >= self.signal_threshold)
                )
                if exit_signal:
                    exit_price = (
                        self._apply_sell_price(current_price) if direction > 0
                        else self._apply_buy_price(current_price)
                    )
                    # Calculate P&L
                    if direction > 0:
                        raw_pnl = (exit_price - entry_price) * abs(position)
                    else:
                        raw_pnl = (entry_price - exit_price) * abs(position)
                    comm = self._trade_commission(abs(position) * entry_price, exit_price)
                    net_pnl = raw_pnl - comm

                    holding_days = (
                        (current_date - entry_date).days if entry_date is not None else 0
                    )
                    trade_pnl_pct = (net_pnl / (entry_price * abs(position))) if entry_price != 0 else 0.0

                    trades.append(Trade(
                        entry_date=entry_date or current_date,
                        exit_date=current_date,
                        entry_price=entry_price,
                        exit_price=exit_price,
                        direction=direction,
                        shares=abs(position),
                        pnl=net_pnl,
                        pnl_pct=trade_pnl_pct,
                        holding_period_days=holding_days,
                        commission=comm,
                    ))
                    equity += net_pnl + (entry_price * abs(position))
                    position = 0.0
                    entry_price = 0.0
                    entry_date = None
                    direction = 0.0

            # --- Equity snapshot ---
            mark = equity + (position * current_price)
            equity_values.append((current_date, mark))

        # --- Close open position at last bar ---
        if position != 0:
            last_price = float(close.iloc[-1])
            last_date = idx[-1] if isinstance(idx[-1], datetime) else datetime.fromtimestamp(idx[-1].timestamp()) if hasattr(idx[-1], 'timestamp') else datetime.now()
            exit_price = (
                self._apply_sell_price(last_price) if direction > 0
                else self._apply_buy_price(last_price)
            )
            if direction > 0:
                raw_pnl = (exit_price - entry_price) * abs(position)
            else:
                raw_pnl = (entry_price - exit_price) * abs(position)
            comm = self._trade_commission(abs(position) * entry_price, exit_price)
            net_pnl = raw_pnl - comm
            holding_days = (last_date - entry_date).days if entry_date is not None else 0
            trade_pnl_pct = (net_pnl / (entry_price * abs(position))) if entry_price != 0 else 0.0

            trades.append(Trade(
                entry_date=entry_date or last_date,
                exit_date=last_date,
                entry_price=entry_price,
                exit_price=exit_price,
                direction=direction,
                shares=abs(position),
                pnl=net_pnl,
                pnl_pct=trade_pnl_pct,
                holding_period_days=holding_days,
                commission=comm,
            ))
            equity += net_pnl + (entry_price * abs(position))
            equity_values[-1] = (last_date, equity)

        # --- Build equity curve ---
        eq_df = pd.DataFrame(equity_values, columns=["date", "equity"])
        eq_df.set_index("date", inplace=True)
        eq_series = eq_df["equity"]

        # --- Compute metrics via metrics module ---
        from src.strategy.metrics import (
            annualized_return,
            avg_win_loss,
            calmar_ratio,
            max_drawdown,
            profit_factor,
            recovery_factor,
            sharpe_ratio,
            sortino_ratio,
            total_return,
            win_rate,
        )

        tr = total_return(eq_series)
        ar = annualized_return(eq_series)
        sr = sharpe_ratio(eq_series)
        so = sortino_ratio(eq_series)
        mdd = max_drawdown(eq_series)
        wr = win_rate(trades)
        pf = profit_factor(trades)
        avg_hold = float(np.mean([t.holding_period_days for t in trades])) if trades else 0.0

        period_start = str(idx[min_bars])[:10] if len(idx) > min_bars else ""
        period_end = str(idx[-1])[:10] if len(idx) > 0 else ""

        return BacktestResult(
            strategy_id=strategy.config.id,
            symbol=symbol or strategy.config.id,
            period=f"{period_start}/{period_end}",
            total_return=tr,
            annualized_return=ar,
            sharpe_ratio=sr,
            sortino_ratio=so,
            max_drawdown=mdd,
            win_rate=wr,
            profit_factor=pf,
            total_trades=len(trades),
            avg_holding_period=avg_hold,
            trade_log=trades,
            equity_curve=eq_series,
        )

    # ------------------------------------------------------------------
    # Batch backtest
    # ------------------------------------------------------------------

    def backtest_all(
        self,
        strategies: Dict[str, BaseStrategy],
        data: pd.DataFrame,
        symbol: str = "",
    ) -> List[BacktestResult]:
        """Run every strategy in *strategies* on the same data."""
        results: List[BacktestResult] = []
        for sid, strat in strategies.items():
            try:
                result = self.backtest(strat, data, symbol=symbol or sid)
                results.append(result)
            except Exception as exc:
                print(f"[backtest_all] {sid}: {exc}")
        return results

    # ------------------------------------------------------------------
    # Ranking & comparison
    # ------------------------------------------------------------------

    @staticmethod
    def rank_strategies(
        results: List[BacktestResult],
        metric: str = "sharpe_ratio",
        ascending: bool = False,
    ) -> List[BacktestResult]:
        """Return *results* sorted by *metric* (default: Sharpe)."""
        def _key(r: BacktestResult) -> float:
            d = r.summary_dict()
            return float(d.get(metric, 0.0))
        return sorted(results, key=_key, reverse=not ascending)

    @staticmethod
    def compare_strategies(
        results: List[BacktestResult],
    ) -> pd.DataFrame:
        """Return a DataFrame comparing key metrics across strategies."""
        rows = []
        for r in results:
            row = r.summary_dict()
            rows.append(row)
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.set_index("strategy_id")
        return df

    # ------------------------------------------------------------------
    # Walk-forward analysis
    # ------------------------------------------------------------------

    def walk_forward(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        symbol: str = "",
        in_sample_pct: float = 0.7,
        n_splits: int = 5,
    ) -> List[BacktestResult]:
        """Walk-forward: split into in-sample / out-of-sample windows."""
        n = len(data)
        split_size = n // n_splits
        results: List[BacktestResult] = []

        for i in range(n_splits):
            start = i * split_size
            end = min(start + split_size, n)
            window = data.iloc[start:end].copy()
            is_end = int(len(window) * in_sample_pct)
            oos = window.iloc[is_end:].copy()
            if len(oos) < strategy.minimum_data_points():
                continue
            res = self.backtest(strategy, oos, symbol=symbol)
            results.append(res)
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_buy_price(self, price: float) -> float:
        """Buy at ask = price + spread."""
        return price * (1.0 + self.commission.spread_pct / 2)

    def _apply_sell_price(self, price: float) -> float:
        """Sell at bid = price - spread."""
        return price * (1.0 - self.commission.spread_pct / 2)

    def _trade_commission(self, notional: float, price: float) -> float:
        """Compute dollar commission for one side of a trade."""
        return (
            self.commission.per_trade_fee
            + notional * 0.0  # placeholder for percentage fee
        )

    def _empty_result(
        self, strategy_id: str, symbol: str, data: pd.DataFrame,
    ) -> BacktestResult:
        """Return a zero-valued result when data is insufficient."""
        period = ""
        if not data.empty:
            period = f"{str(data.index[0])[:10]}/{str(data.index[-1])[:10]}"
        return BacktestResult(
            strategy_id=strategy_id,
            symbol=symbol,
            period=period,
            total_return=0.0,
            annualized_return=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            total_trades=0,
            avg_holding_period=0.0,
            trade_log=[],
            equity_curve=pd.Series(dtype=float),
        )
