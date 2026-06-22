"""Reporting engine — generates periodic learning reports."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.learning.insights import InsightsEngine, InsightsReport
from src.learning.tracker import StrategyPerformance, Tracker


@dataclass
class LearningReport:
    """A periodic learning report.

    Attributes:
        report_type: 'weekly', 'monthly', 'quarterly', or 'annual'.
        generated_at: When the report was generated.
        period_start: Start of the reporting period.
        period_end: End of the reporting period.
        performance_summary: Per-strategy performance summary.
        weight_changes: Dict of strategy_id -> (old_weight, new_weight).
        insights: The insights report.
        regime_summary: Current regime and recent changes.
        recommendations: List of actionable recommendations.
        narrative: Human-readable narrative of the report.
    """

    report_type: str = ""
    generated_at: datetime = field(default_factory=datetime.utcnow)
    period_start: datetime = field(default_factory=datetime.utcnow)
    period_end: datetime = field(default_factory=datetime.utcnow)
    performance_summary: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    weight_changes: Dict[str, tuple[float, float]] = field(default_factory=dict)
    insights: Optional[InsightsReport] = None
    regime_summary: str = ""
    recommendations: List[str] = field(default_factory=list)
    narrative: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "report_type": self.report_type,
            "generated_at": self.generated_at.isoformat(),
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "performance_summary": self.performance_summary,
            "weight_changes": {
                k: {"old": v[0], "new": v[1]}
                for k, v in self.weight_changes.items()
            },
            "regime_summary": self.regime_summary,
            "recommendations": self.recommendations,
            "narrative": self.narrative,
        }


class ReportingEngine:
    """Generates periodic learning reports.

    Usage:
        reporter = ReportingEngine(tracker, insights_engine)
        weekly = reporter.weekly_report()
        monthly = reporter.monthly_rebalance_summary()
        quarterly = reporter.quarterly_review()
    """

    def __init__(
        self,
        tracker: Tracker,
        insights_engine: InsightsEngine,
        current_weights: Optional[Dict[str, float]] = None,
        previous_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        """Initialize the reporting engine.

        Args:
            tracker: Performance tracker with recorded outcomes.
            insights_engine: InsightsEngine for generating insights.
            current_weights: Current strategy weights.
            previous_weights: Previous strategy weights (for change tracking).
        """
        self._tracker = tracker
        self._insights = insights_engine
        self._current_weights = current_weights or {}
        self._previous_weights = previous_weights or {}

    def weekly_report(self) -> LearningReport:
        """Generate a weekly learning report.

        Covers: what changed, why, key metrics.

        Returns:
            LearningReport for the past week.
        """
        now = datetime.utcnow()
        week_start = now - timedelta(weeks=1)

        period = "1w"
        performance = self._tracker.get_all_performance(period)
        insights = self._insights.get_insights(period)

        perf_summary = self._format_performance(performance)
        weight_changes = self._compute_weight_changes()
        recommendations = self._generate_recommendations(insights)
        narrative = self._build_weekly_narrative(performance, insights)

        return LearningReport(
            report_type="weekly",
            generated_at=now,
            period_start=week_start,
            period_end=now,
            performance_summary=perf_summary,
            weight_changes=weight_changes,
            insights=insights,
            regime_summary=self._current_regime_summary(),
            recommendations=recommendations,
            narrative=narrative,
        )

    def monthly_rebalance_summary(self) -> LearningReport:
        """Generate a monthly strategy rebalance summary.

        Covers: weight changes, performance drivers, rebalance rationale.

        Returns:
            LearningReport for the past month.
        """
        now = datetime.utcnow()
        month_start = now - timedelta(days=30)

        period = "1m"
        performance = self._tracker.get_all_performance(period)
        insights = self._insights.get_insights(period)

        perf_summary = self._format_performance(performance)
        weight_changes = self._compute_weight_changes()
        recommendations = self._generate_recommendations(insights)
        narrative = self._build_monthly_narrative(performance, insights, weight_changes)

        return LearningReport(
            report_type="monthly",
            generated_at=now,
            period_start=month_start,
            period_end=now,
            performance_summary=perf_summary,
            weight_changes=weight_changes,
            insights=insights,
            regime_summary=self._current_regime_summary(),
            recommendations=recommendations,
            narrative=narrative,
        )

    def quarterly_review(self) -> LearningReport:
        """Generate a quarterly performance review.

        Covers: long-term trends, strategy retirement candidates,
        system health assessment.

        Returns:
            LearningReport for the past quarter.
        """
        now = datetime.utcnow()
        quarter_start = now - timedelta(days=90)

        period = "3m"
        performance = self._tracker.get_all_performance(period)
        insights = self._insights.get_insights(period)

        perf_summary = self._format_performance(performance)
        weight_changes = self._compute_weight_changes()
        recommendations = self._generate_quarterly_recommendations(
            performance, insights
        )
        narrative = self._build_quarterly_narrative(
            performance, insights, weight_changes
        )

        return LearningReport(
            report_type="quarterly",
            generated_at=now,
            period_start=quarter_start,
            period_end=now,
            performance_summary=perf_summary,
            weight_changes=weight_changes,
            insights=insights,
            regime_summary=self._current_regime_summary(),
            recommendations=recommendations,
            narrative=narrative,
        )

    # ------------------------------------------------------------------
    # Narrative builders
    # ------------------------------------------------------------------

    def _build_weekly_narrative(
        self,
        performance: Dict[str, StrategyPerformance],
        insights: InsightsReport,
    ) -> str:
        """Build human-readable weekly narrative."""
        parts: List[str] = []
        parts.append("=== Weekly Learning Report ===\n")

        if not performance:
            parts.append("No trade activity this week.")
            return "\n".join(parts)

        n_strategies = len(performance)
        total_trades = sum(p.signals_taken for p in performance.values())
        parts.append(
            f"Active strategies: {n_strategies}, "
            f"Total trades: {total_trades}"
        )

        if insights.best_strategies:
            top = insights.best_strategies[0]
            p = performance.get(top)
            if p:
                parts.append(
                    f"Top performer: {top} "
                    f"(Sharpe {p.sharpe_ratio:.2f}, "
                    f"win rate {p.win_rate:.1%})"
                )

        if insights.worst_strategies:
            bot = insights.worst_strategies[0]
            p = performance.get(bot)
            if p:
                parts.append(
                    f"Needs attention: {bot} "
                    f"(Sharpe {p.sharpe_ratio:.2f}, "
                    f"win rate {p.win_rate:.1%})"
                )

        parts.append(f"\nSystem trend: {insights.system_trend}")

        if insights.loss_patterns:
            parts.append("\nLoss patterns identified:")
            for pattern in insights.loss_patterns[:3]:
                parts.append(f"  - {pattern}")

        return "\n".join(parts)

    def _build_monthly_narrative(
        self,
        performance: Dict[str, StrategyPerformance],
        insights: InsightsReport,
        weight_changes: Dict[str, tuple[float, float]],
    ) -> str:
        """Build human-readable monthly narrative."""
        parts: List[str] = []
        parts.append("=== Monthly Rebalance Summary ===\n")

        if weight_changes:
            parts.append("Weight adjustments:")
            for sid, (old, new) in sorted(weight_changes.items()):
                delta = new - old
                direction = "increased" if delta > 0 else "decreased"
                parts.append(
                    f"  {sid}: {old:.1%} -> {new:.1%} ({direction} by {abs(delta):.1%})"
                )
        else:
            parts.append("No weight changes this period.")

        if insights.regime_favorites:
            parts.append("\nRegime-specific recommendations:")
            for regime, strats in insights.regime_favorites.items():
                parts.append(f"  {regime}: {', '.join(strats)}")

        parts.append(f"\nSystem trend: {insights.system_trend}")
        return "\n".join(parts)

    def _build_quarterly_narrative(
        self,
        performance: Dict[str, StrategyPerformance],
        insights: InsightsReport,
        weight_changes: Dict[str, tuple[float, float]],
    ) -> str:
        """Build human-readable quarterly narrative."""
        parts: List[str] = []
        parts.append("=== Quarterly Performance Review ===\n")

        if performance:
            avg_sharpe = sum(p.sharpe_ratio for p in performance.values()) / len(
                performance
            )
            avg_win = sum(p.win_rate for p in performance.values()) / len(performance)
            parts.append(
                f"Overall: {len(performance)} strategies, "
                f"avg Sharpe {avg_sharpe:.2f}, "
                f"avg win rate {avg_win:.1%}"
            )

        # Retirement candidates
        for sid, perf in performance.items():
            if perf.signals_taken >= 10 and perf.sharpe_ratio < -0.5:
                parts.append(
                    f"\n⚠ Retirement candidate: {sid} "
                    f"(Sharpe {perf.sharpe_ratio:.2f}, "
                    f"{perf.signals_taken} trades)"
                )

        parts.append(f"\nSystem trend: {insights.system_trend}")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _format_performance(
        self, performance: Dict[str, StrategyPerformance]
    ) -> Dict[str, Dict[str, Any]]:
        """Format performance for report output."""
        result: Dict[str, Dict[str, Any]] = {}
        for sid, p in performance.items():
            result[sid] = p.to_dict()
        return result

    def _compute_weight_changes(self) -> Dict[str, tuple[float, float]]:
        """Compute weight changes between previous and current."""
        changes: Dict[str, tuple[float, float]] = {}
        all_ids = set(self._current_weights.keys()) | set(
            self._previous_weights.keys()
        )
        for sid in all_ids:
            old = self._previous_weights.get(sid, 0.0)
            new = self._current_weights.get(sid, 0.0)
            if abs(new - old) > 0.001:
                changes[sid] = (old, new)
        return changes

    def _generate_recommendations(
        self, insights: InsightsReport
    ) -> List[str]:
        """Generate actionable recommendations from insights."""
        recs: List[str] = []
        for insight in insights.insights:
            if insight.recommendation:
                recs.append(
                    f"[{insight.category}] {insight.strategy_id}: "
                    f"{insight.recommendation}"
                )
        return recs[:10]  # Cap at 10

    def _generate_quarterly_recommendations(
        self,
        performance: Dict[str, StrategyPerformance],
        insights: InsightsReport,
    ) -> List[str]:
        """Generate quarterly-specific recommendations."""
        recs: List[str] = []

        for sid, perf in performance.items():
            if perf.signals_taken >= 10 and perf.sharpe_ratio < -0.5:
                recs.append(
                    f"RETIRE: {sid} — Sharpe {perf.sharpe_ratio:.2f} "
                    f"over {perf.signals_taken} trades is unacceptable."
                )

        for sid, perf in performance.items():
            if perf.signals_taken >= 10 and perf.win_rate > 0.65:
                recs.append(
                    f"EXPAND: {sid} — {perf.win_rate:.1%} win rate "
                    f"deserves increased allocation."
                )

        recs.extend(self._generate_recommendations(insights))
        return recs[:15]

    def _current_regime_summary(self) -> str:
        """Get a brief summary of the current regime."""
        # In production, this would query the RegimeDetector.
        return "Regime detection available via RegimeDetector.detect()"
