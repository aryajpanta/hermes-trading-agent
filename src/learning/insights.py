"""Insights engine — analyzes strategy performance to generate actionable insights."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.learning.tracker import StrategyPerformance, TradeOutcome, Tracker


@dataclass
class StrategyInsight:
    """A single insight about a strategy.

    Attributes:
        strategy_id: Strategy the insight relates to.
        category: Insight category ('best', 'worst', 'improving',
            'degrading', 'regime_sensitive', 'loss_pattern').
        summary: One-line summary.
        details: Detailed explanation.
        recommendation: Suggested action.
    """

    strategy_id: str = ""
    category: str = ""
    summary: str = ""
    details: str = ""
    recommendation: str = ""


@dataclass
class InsightsReport:
    """Complete insights report.

    Attributes:
        insights: List of individual insights.
        best_strategies: Strategy IDs performing best.
        worst_strategies: Strategy IDs performing worst.
        regime_favorites: Which strategies work best in each regime.
        loss_patterns: Identified patterns in losing trades.
        system_trend: Whether the overall system is improving or degrading.
    """

    insights: List[StrategyInsight] = field(default_factory=list)
    best_strategies: List[str] = field(default_factory=list)
    worst_strategies: List[str] = field(default_factory=list)
    regime_favorites: Dict[str, List[str]] = field(default_factory=dict)
    loss_patterns: List[str] = field(default_factory=list)
    system_trend: str = "stable"


class InsightsEngine:
    """Analyzes performance data to generate human-readable insights.

    Usage:
        engine = InsightsEngine(tracker)
        report = engine.get_insights()
    """

    def __init__(self, tracker: Tracker) -> None:
        """Initialize with a performance tracker.

        Args:
            tracker: Tracker instance with recorded trade outcomes.
        """
        self._tracker = tracker

    def get_insights(self, period: str = "1m") -> InsightsReport:
        """Generate a full insights report.

        Args:
            period: Lookback period for analysis.

        Returns:
            InsightsReport with all insights.
        """
        all_perf = self._tracker.get_all_performance(period)
        insights: List[StrategyInsight] = []

        # 1. Best and worst strategies
        best, worst = self._rank_strategies(all_perf)
        insights.extend(self._generate_ranking_insights(best, worst, all_perf))

        # 2. Regime-specific favorites
        regime_favorites = self._find_regime_favorites(period)
        insights.extend(self._generate_regime_insights(regime_favorites))

        # 3. Loss patterns
        loss_patterns = self._find_loss_patterns(period)
        insights.extend(self._generate_loss_insights(loss_patterns))

        # 4. System trend
        system_trend = self._assess_system_trend(period)
        insights.append(
            StrategyInsight(
                strategy_id="system",
                category="system_trend",
                summary=f"System is {system_trend}",
                details=self._trend_details(period),
                recommendation=self._trend_recommendation(system_trend),
            )
        )

        return InsightsReport(
            insights=insights,
            best_strategies=best,
            worst_strategies=worst,
            regime_favorites=regime_favorites,
            loss_patterns=[p["description"] for p in loss_patterns],
            system_trend=system_trend,
        )

    def get_strategy_insight(
        self, strategy_id: str, period: str = "1m"
    ) -> StrategyInsight:
        """Get detailed insight for a single strategy.

        Args:
            strategy_id: Strategy to analyze.
            period: Lookback period.

        Returns:
            StrategyInsight for the strategy.
        """
        perf = self._tracker.get_performance(strategy_id, period)
        all_perf = self._tracker.get_all_performance(period)

        # Rank this strategy
        ranked = sorted(
            all_perf.keys(),
            key=lambda s: all_perf[s].sharpe_ratio,
            reverse=True,
        )
        rank = ranked.index(strategy_id) + 1 if strategy_id in ranked else 0
        total = len(ranked)

        if perf.win_rate >= 0.6 and perf.sharpe_ratio > 1.0:
            category = "best"
            rec = "Increase weight allocation for this strategy."
        elif perf.win_rate < 0.4 or perf.sharpe_ratio < 0:
            category = "worst"
            rec = "Consider reducing weight or reviewing parameters."
        elif perf.signals_taken < 5:
            category = "data_scarce"
            rec = "More trades needed for reliable assessment."
        else:
            category = "average"
            rec = "Strategy performing within normal range."

        return StrategyInsight(
            strategy_id=strategy_id,
            category=category,
            summary=(
                f"Rank {rank}/{total}: {perf.win_rate:.1%} win rate, "
                f"Sharpe {perf.sharpe_ratio:.2f}, "
                f"Avg return {perf.avg_return:.2%}"
            ),
            details=(
                f"Over {period}: {perf.signals_taken} trades from "
                f"{perf.total_signals} signals. "
                f"Max drawdown: {perf.max_drawdown:.2%}."
            ),
            recommendation=rec,
        )

    # ------------------------------------------------------------------
    # Internal analysis methods
    # ------------------------------------------------------------------

    def _rank_strategies(
        self, performance: Dict[str, StrategyPerformance]
    ) -> tuple[List[str], List[str]]:
        """Rank strategies and identify best/worst.

        Args:
            performance: All strategy performance data.

        Returns:
            Tuple of (best_strategy_ids, worst_strategy_ids).
        """
        if not performance:
            return [], []

        # Sort by Sharpe ratio (primary) then win rate (secondary)
        ranked = sorted(
            performance.keys(),
            key=lambda s: (
                performance[s].sharpe_ratio,
                performance[s].win_rate,
            ),
            reverse=True,
        )

        # Top 3 and bottom 3 (or fewer if not enough strategies)
        n = len(ranked)
        top_n = min(3, n)
        bot_n = min(3, n)

        best = ranked[:top_n]
        worst = ranked[-bot_n:] if bot_n > 0 else []

        # Don't report same strategy as both best and worst
        if n <= 3:
            worst = []

        return best, worst

    def _generate_ranking_insights(
        self,
        best: List[str],
        worst: List[str],
        performance: Dict[str, StrategyPerformance],
    ) -> List[StrategyInsight]:
        """Generate insights from strategy rankings."""
        insights: List[StrategyInsight] = []

        if best:
            top = best[0]
            p = performance[top]
            insights.append(
                StrategyInsight(
                    strategy_id=top,
                    category="best",
                    summary=(
                        f"Top performer: {p.win_rate:.1%} win rate, "
                        f"Sharpe {p.sharpe_ratio:.2f}"
                    ),
                    details=(
                        f"Over the period: {p.signals_taken} trades, "
                        f"avg return {p.avg_return:.2%}, "
                        f"max drawdown {p.max_drawdown:.2%}."
                    ),
                    recommendation="Consider increasing allocation to this strategy.",
                )
            )

        if worst:
            bottom = worst[-1]
            p = performance[bottom]
            insights.append(
                StrategyInsight(
                    strategy_id=bottom,
                    category="worst",
                    summary=(
                        f"Underperforming: {p.win_rate:.1%} win rate, "
                        f"Sharpe {p.sharpe_ratio:.2f}"
                    ),
                    details=(
                        f"Over the period: {p.signals_taken} trades, "
                        f"avg return {p.avg_return:.2%}, "
                        f"max drawdown {p.max_drawdown:.2%}."
                    ),
                    recommendation="Review parameters or reduce allocation.",
                )
            )

        return insights

    def _find_regime_favorites(self, period: str) -> Dict[str, List[str]]:
        """Find which strategies perform best in each market regime.

        Args:
            period: Lookback period.

        Returns:
            Dictionary mapping regime -> list of best strategy IDs.
        """
        regimes = ["bull", "bear", "sideways", "high_volatility"]
        favorites: Dict[str, List[str]] = {}

        for regime in regimes:
            outcomes = self._tracker.get_outcomes(regime=regime, period=period)
            if not outcomes:
                continue

            # Aggregate returns by strategy in this regime
            strat_returns: Dict[str, List[float]] = {}
            for o in outcomes:
                if o.strategy_id not in strat_returns:
                    strat_returns[o.strategy_id] = []
                strat_returns[o.strategy_id].append(o.return_pct)

            # Rank by average return
            ranked = sorted(
                strat_returns.keys(),
                key=lambda s: (
                    sum(strat_returns[s]) / len(strat_returns[s])
                    if strat_returns[s]
                    else 0
                ),
                reverse=True,
            )

            if ranked:
                # Top 2 strategies for this regime
                favorites[regime] = ranked[:2]

        return favorites

    def _generate_regime_insights(
        self, regime_favorites: Dict[str, List[str]]
    ) -> List[StrategyInsight]:
        """Generate insights from regime-specific performance."""
        insights: List[StrategyInsight] = []

        for regime, strategies in regime_favorites.items():
            if strategies:
                insights.append(
                    StrategyInsight(
                        strategy_id=strategies[0],
                        category="regime_sensitive",
                        summary=(
                            f"Best in {regime} markets: "
                            f"{', '.join(strategies)}"
                        ),
                        details=(
                            f"These strategies show the highest returns "
                            f"during {regime} conditions."
                        ),
                        recommendation=(
                            f"Increase allocation to {strategies[0]} "
                            f"when {regime} regime is detected."
                        ),
                    )
                )

        return insights

    def _find_loss_patterns(self, period: str) -> List[Dict[str, Any]]:
        """Identify patterns in losing trades.

        Args:
            period: Lookback period.

        Returns:
            List of identified loss patterns.
        """
        outcomes = self._tracker.get_outcomes(period=period)
        losers = [o for o in outcomes if o.return_pct < 0]

        if not losers:
            return []

        patterns: List[Dict[str, Any]] = []

        # Pattern 1: Strategies with high loss rates
        strat_losses: Dict[str, int] = {}
        strat_total: Dict[str, int] = {}
        for o in outcomes:
            strat_total[o.strategy_id] = strat_total.get(o.strategy_id, 0) + 1
            if o.return_pct < 0:
                strat_losses[o.strategy_id] = strat_losses.get(o.strategy_id, 0) + 1

        for sid in strat_losses:
            total = strat_total.get(sid, 1)
            loss_rate = strat_losses[sid] / total
            if loss_rate > 0.6:
                patterns.append({
                    "type": "high_loss_rate",
                    "strategy_id": sid,
                    "description": (
                        f"Strategy '{sid}' has {loss_rate:.0%} loss rate "
                        f"({strat_losses[sid]}/{total} trades)"
                    ),
                })

        # Pattern 2: Large losses
        large_losses = [o for o in losers if o.return_pct < -0.05]
        if len(large_losses) > 2:
            avg_large = sum(o.return_pct for o in large_losses) / len(large_losses)
            patterns.append({
                "type": "large_losses",
                "description": (
                    f"{len(large_losses)} trades with >5% loss "
                    f"(avg: {avg_large:.2%})"
                ),
            })

        # Pattern 3: Regime-specific losses
        regime_losses: Dict[str, int] = {}
        for o in losers:
            regime_losses[o.regime] = regime_losses.get(o.regime, 0) + 1
        for regime, count in regime_losses.items():
            if count > len(losers) * 0.4:
                patterns.append({
                    "type": "regime_concentration",
                    "description": (
                        f"{count}/{len(losers)} losses occurred in "
                        f"{regime} regime"
                    ),
                })

        return patterns

    def _generate_loss_insights(
        self, patterns: List[Dict[str, Any]]
    ) -> List[StrategyInsight]:
        """Generate insights from loss patterns."""
        insights: List[StrategyInsight] = []

        for pattern in patterns:
            strategy_id = pattern.get("strategy_id", "system")
            insights.append(
                StrategyInsight(
                    strategy_id=strategy_id,
                    category="loss_pattern",
                    summary=pattern["description"],
                    details=f"Pattern type: {pattern['type']}",
                    recommendation=self._loss_pattern_recommendation(pattern),
                )
            )

        return insights

    def _assess_system_trend(self, period: str) -> str:
        """Assess whether the system is improving or degrading.

        Compares recent performance to older performance within the period.

        Args:
            period: Lookback period.

        Returns:
            'improving', 'degrading', or 'stable'.
        """
        all_perf = self._tracker.get_all_performance(period)
        if not all_perf:
            return "stable"

        # Compare 1w vs 3m performance for each strategy
        recent_perf = self._tracker.get_all_performance("1w")
        older_perf = self._tracker.get_all_performance("3m")

        improvements = 0
        degradations = 0

        for sid in all_perf:
            if sid in recent_perf and sid in older_perf:
                r = recent_perf[sid]
                o = older_perf[sid]
                # Compare win rates and Sharpe
                if r.sharpe_ratio > o.sharpe_ratio + 0.1:
                    improvements += 1
                elif r.sharpe_ratio < o.sharpe_ratio - 0.1:
                    degradations += 1

        if improvements > degradations + 1:
            return "improving"
        elif degradations > improvements + 1:
            return "degrading"
        return "stable"

    def _trend_details(self, period: str) -> str:
        """Generate details about the system trend."""
        all_perf = self._tracker.get_all_performance(period)
        if not all_perf:
            return "No performance data available."

        total_trades = sum(p.signals_taken for p in all_perf.values())
        avg_sharpe = (
            sum(p.sharpe_ratio for p in all_perf.values()) / len(all_perf)
            if all_perf
            else 0
        )
        avg_win_rate = (
            sum(p.win_rate for p in all_perf.values()) / len(all_perf)
            if all_perf
            else 0
        )

        return (
            f"{len(all_perf)} strategies tracked, "
            f"{total_trades} total trades, "
            f"avg Sharpe {avg_sharpe:.2f}, "
            f"avg win rate {avg_win_rate:.1%}."
        )

    @staticmethod
    def _trend_recommendation(trend: str) -> str:
        """Recommendation based on system trend."""
        if trend == "improving":
            return "System is improving. Continue current approach."
        elif trend == "degrading":
            return (
                "System is degrading. Review strategy parameters, "
                "consider rebalancing weights, or retire underperformers."
            )
        return "System is stable. Monitor for changes."

    @staticmethod
    def _loss_pattern_recommendation(pattern: Dict[str, Any]) -> str:
        """Recommendation based on loss pattern type."""
        ptype = pattern.get("type", "")
        if ptype == "high_loss_rate":
            return "Review entry conditions and consider tightening filters."
        elif ptype == "large_losses":
            return "Review stop-loss placement and position sizing."
        elif ptype == "regime_concentration":
            return "Consider regime-based strategy switching."
        return "Review trade journal for additional patterns."
