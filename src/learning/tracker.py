"""Performance tracker — records trade outcomes and computes per-strategy metrics."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np


@dataclass
class TradeOutcome:
    """Result of a single executed trade.

    Attributes:
        trade_id: Unique identifier for the trade.
        strategy_id: Strategy that generated the signal.
        symbol: Asset symbol traded.
        direction: 'LONG' or 'SHORT'.
        entry_price: Price at entry.
        exit_price: Price at exit (0 if still open).
        quantity: Units traded.
        entry_time: When the trade was opened.
        exit_time: When the trade was closed (None if open).
        pnl: Realized P&L in dollars.
        return_pct: Percentage return on the trade.
        regime: Market regime at time of trade.
    """

    trade_id: str = ""
    strategy_id: str = ""
    symbol: str = ""
    direction: str = "LONG"
    entry_price: float = 0.0
    exit_price: float = 0.0
    quantity: float = 0.0
    entry_time: datetime = field(default_factory=datetime.utcnow)
    exit_time: Optional[datetime] = None
    pnl: float = 0.0
    return_pct: float = 0.0
    regime: str = "unknown"


@dataclass
class StrategyPerformance:
    """Aggregated performance metrics for a strategy over a period.

    Attributes:
        strategy_id: Strategy identifier.
        period: Lookback window ('1d', '1w', '1m', '3m', '1y').
        total_signals: Total signals generated.
        signals_taken: Signals that resulted in trades.
        win_rate: Fraction of winning trades.
        avg_return: Average return per trade (decimal).
        sharpe_ratio: Annualized Sharpe ratio of trade returns.
        max_drawdown: Maximum peak-to-trough drawdown (decimal).
        last_updated: Timestamp of last recalculation.
    """

    strategy_id: str = ""
    period: str = "1m"
    total_signals: int = 0
    signals_taken: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, object]:
        """Serialize to dictionary."""
        return {
            "strategy_id": self.strategy_id,
            "period": self.period,
            "total_signals": self.total_signals,
            "signals_taken": self.signals_taken,
            "win_rate": self.win_rate,
            "avg_return": self.avg_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "last_updated": self.last_updated.isoformat(),
        }


# Period string -> timedelta mapping
_PERIOD_MAP: Dict[str, timedelta] = {
    "1d": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "1m": timedelta(days=30),
    "3m": timedelta(days=90),
    "1y": timedelta(days=365),
}

_DEFAULT_PERIODS = ["1d", "1w", "1m", "3m", "1y"]


class Tracker:
    """Records trade outcomes and computes per-strategy performance metrics.

    Usage:
        tracker = Tracker()
        tracker.track_outcome(trade)
        perf = tracker.get_performance("ma_crossover", period="1m")
    """

    def __init__(self) -> None:
        self._outcomes: List[TradeOutcome] = []
        self._signals_generated: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def track_outcome(self, outcome: TradeOutcome) -> None:
        """Record a completed trade outcome.

        Args:
            outcome: TradeOutcome with trade details and P&L.
        """
        self._outcomes.append(outcome)

    def record_signal(self, strategy_id: str) -> None:
        """Record that a strategy generated a signal (whether taken or not).

        Args:
            strategy_id: The strategy that generated the signal.
        """
        self._signals_generated[strategy_id] = (
            self._signals_generated.get(strategy_id, 0) + 1
        )

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def get_outcomes(
        self,
        strategy_id: Optional[str] = None,
        period: Optional[str] = None,
        regime: Optional[str] = None,
    ) -> List[TradeOutcome]:
        """Retrieve trade outcomes with optional filters.

        Args:
            strategy_id: Filter by strategy.
            period: Filter by lookback period ('1w', '1m', etc.).
            regime: Filter by market regime at time of trade.

        Returns:
            Filtered list of TradeOutcome.
        """
        now = datetime.utcnow()
        results = self._outcomes

        if strategy_id is not None:
            results = [o for o in results if o.strategy_id == strategy_id]

        if regime is not None:
            results = [o for o in results if o.regime == regime]

        if period is not None and period in _PERIOD_MAP:
            cutoff = now - _PERIOD_MAP[period]
            results = [o for o in results if o.entry_time >= cutoff]

        return results

    def get_performance(
        self, strategy_id: str, period: str = "1m"
    ) -> StrategyPerformance:
        """Compute StrategyPerformance for a strategy over a period.

        Args:
            strategy_id: Strategy to compute metrics for.
            period: Lookback window ('1d', '1w', '1m', '3m', '1y').

        Returns:
            StrategyPerformance with computed metrics.
        """
        trades = self.get_outcomes(strategy_id=strategy_id, period=period)
        total_signals = self._signals_generated.get(strategy_id, 0)
        signals_taken = len(trades)

        if not trades:
            return StrategyPerformance(
                strategy_id=strategy_id,
                period=period,
                total_signals=total_signals,
                signals_taken=0,
                win_rate=0.0,
                avg_return=0.0,
                sharpe_ratio=0.0,
                max_drawdown=0.0,
                last_updated=datetime.utcnow(),
            )

        returns = [t.return_pct for t in trades]
        wins = sum(1 for r in returns if r > 0)

        win_rate = wins / len(returns)
        avg_return = float(np.mean(returns))

        sharpe = self._compute_sharpe(returns)
        max_dd = self._compute_max_drawdown(returns)

        return StrategyPerformance(
            strategy_id=strategy_id,
            period=period,
            total_signals=total_signals,
            signals_taken=signals_taken,
            win_rate=win_rate,
            avg_return=avg_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_dd,
            last_updated=datetime.utcnow(),
        )

    def get_all_performance(
        self, period: str = "1m"
    ) -> Dict[str, StrategyPerformance]:
        """Compute performance for all strategies with recorded trades.

        Args:
            period: Lookback window.

        Returns:
            Dictionary mapping strategy_id to StrategyPerformance.
        """
        strategy_ids = set()
        for o in self._outcomes:
            strategy_ids.add(o.strategy_id)
        for sid in self._signals_generated:
            strategy_ids.add(sid)

        result: Dict[str, StrategyPerformance] = {}
        for sid in sorted(strategy_ids):
            result[sid] = self.get_performance(sid, period)
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_sharpe(returns: List[float], risk_free_daily: float = 0.04 / 252) -> float:
        """Compute annualized Sharpe ratio from a list of trade returns.

        Args:
            returns: List of per-trade returns (decimal).
            risk_free_daily: Daily risk-free rate.

        Returns:
            Annualized Sharpe ratio.
        """
        if len(returns) < 2:
            return 0.0
        arr = np.array(returns, dtype=float)
        std = float(np.std(arr, ddof=1))
        if std == 0:
            return 0.0
        mean_excess = float(np.mean(arr)) - risk_free_daily
        return float(mean_excess / std * np.sqrt(252))

    @staticmethod
    def _compute_max_drawdown(returns: List[float]) -> float:
        """Compute maximum drawdown from a series of returns.

        Args:
            returns: List of per-trade returns (decimal).

        Returns:
            Maximum drawdown as a positive decimal (e.g., 0.10 = 10%).
        """
        if not returns:
            return 0.0
        equity = [1.0]
        for r in returns:
            equity.append(equity[-1] * (1.0 + r))
        peak = equity[0]
        max_dd = 0.0
        for v in equity:
            if v > peak:
                peak = v
            dd = (peak - v) / peak
            if dd > max_dd:
                max_dd = dd
        return max_dd
