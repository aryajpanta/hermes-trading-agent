"""Decision Engine — combines strategy signals, applies risk management, and generates recommendations."""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.decision.logging import (
    clear_decision_logs,
    format_recommendation,
    get_decision_count,
    get_decision_logs,
    log_decision,
)
from src.decision.models import (
    Direction,
    PortfolioPosition,
    PortfolioState,
    RiskConfig,
    StrategyPerformance,
    TradeRecommendation,
)
from src.decision.position_sizing import PositionSizeResult, calculate_position_size
from src.decision.risk import RiskCheckResult, run_all_risk_checks
from src.decision.signals import AggregatedSignal, aggregate_signals, direction_from_signal
from src.strategy import evaluate as strategy_evaluate
from src.strategy.library import list_strategies, load_strategies
from src.strategy.signals import Signal

logger = logging.getLogger("decision_engine")


@dataclass
class AnalysisResult:
    """Full result of analyzing a symbol.

    Attributes:
        symbol: The symbol analyzed.
        aggregated: The aggregated signal.
        recommendation: The final trade recommendation (None if HOLD/no-trade).
        risk_result: Risk check results.
        position_size: Position sizing result.
        signals: Raw signals from each strategy.
        reasoning: Human-readable reasoning.
    """

    symbol: str = ""
    aggregated: Optional[AggregatedSignal] = None
    recommendation: Optional[TradeRecommendation] = None
    risk_result: Optional[RiskCheckResult] = None
    position_size: Optional[PositionSizeResult] = None
    signals: List[Signal] = field(default_factory=list)
    reasoning: str = ""


class DecisionEngine:
    """Main decision engine that orchestrates signal collection, aggregation,
    risk management, and trade recommendation generation.

    Usage:
        engine = DecisionEngine()
        result = engine.analyze("AAPL", data, symbol="AAPL")
        print(result.recommendation)
    """

    def __init__(
        self,
        risk_config: Optional[RiskConfig] = None,
        strategy_performance: Optional[Dict[str, StrategyPerformance]] = None,
        portfolio: Optional[PortfolioState] = None,
        strategy_ids: Optional[List[str]] = None,
    ) -> None:
        """Initialize the decision engine.

        Args:
            risk_config: Risk management configuration. Uses defaults if None.
            strategy_performance: Historical performance data per strategy.
                Used for weighting signals. If None, equal weights.
            portfolio: Current portfolio state. Uses empty portfolio if None.
            strategy_ids: List of strategy IDs to evaluate.
                If None, uses all registered strategies.
        """
        self.risk_config = risk_config or RiskConfig()
        self.strategy_performance = strategy_performance or {}
        self.portfolio = portfolio or PortfolioState()
        self._strategy_ids = strategy_ids

    def _collect_signals(
        self, data: pd.DataFrame, symbol: str
    ) -> List[Signal]:
        """Collect signals from all active strategies for a symbol.

        Args:
            data: OHLCV DataFrame with enough bars for all strategies.
            symbol: Asset symbol.

        Returns:
            List of signals from strategies that produced valid signals.
        """
        # Load strategy configs if needed
        load_strategies()

        if self._strategy_ids is not None:
            ids = self._strategy_ids
        else:
            # Use all registered strategies
            strategies = list_strategies()
            ids = [s.id for s in strategies]

        signals: List[Signal] = []
        for sid in ids:
            try:
                signal = strategy_evaluate(sid, data, symbol=symbol)
                # Only include signals with non-zero confidence
                if signal.confidence > 0:
                    signals.append(signal)
            except Exception as e:
                logger.warning("Strategy '%s' failed: %s", sid, e)
                continue

        return signals

    def _determine_sector(self, symbol: str) -> str:
        """Determine sector for correlation checking.

        Simple heuristic based on symbol. In production, this would
        query a sector mapping database.

        Args:
            symbol: Asset ticker.

        Returns:
            Sector string.
        """
        # Simple heuristic — in production, query a sector map
        symbol_upper = symbol.upper()
        if symbol_upper in ("SPY", "QQQ", "DIA", "IWM", "VTI"):
            return "index"
        if symbol_upper in ("GLD", "SLV", "USO", "USL"):
            return "commodity"
        if symbol_upper in ("TLT", "IEF", "SHY", "BND"):
            return "bond"
        # Default: use the symbol itself as sector (each unique)
        return symbol_upper

    def _build_recommendation(
        self,
        symbol: str,
        agg: AggregatedSignal,
        direction: Direction,
        entry_price: float,
        position_size: PositionSizeResult,
        atr: Optional[float] = None,
    ) -> TradeRecommendation:
        """Build a TradeRecommendation from aggregated signal data.

        Args:
            symbol: Asset symbol.
            agg: Aggregated signal result.
            direction: Trade direction enum.
            entry_price: Current price for entry.
            position_size: Position sizing result.
            atr: Average True Range for stop/take-profit calculation.

        Returns:
            Complete TradeRecommendation.
        """
        atr_val = atr if atr is not None else entry_price * 0.02  # 2% fallback

        if direction == Direction.BUY:
            stop_loss = entry_price - self.risk_config.stop_loss_atr_multiple * atr_val
            take_profit = entry_price + self.risk_config.stop_loss_atr_multiple * atr_val * 2.0
        elif direction == Direction.SELL:
            stop_loss = entry_price + self.risk_config.stop_loss_atr_multiple * atr_val
            take_profit = entry_price - self.risk_config.stop_loss_atr_multiple * atr_val * 2.0
        else:
            stop_loss = entry_price
            take_profit = entry_price

        # Risk/Reward ratio
        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)
        rr_ratio = reward / risk if risk > 0 else 0.0

        reasoning_parts = [
            f"Aggregated signal direction: {agg.direction:.3f} "
            f"(confidence: {agg.confidence:.3f}).",
            f"{len(agg.agreeing)} strategies agree: {', '.join(agg.agreeing)}.",
        ]
        if agg.disagreeing:
            reasoning_parts.append(
                f"{len(agg.disagreeing)} strategies disagree: {', '.join(agg.disagreeing)}."
            )
        reasoning_parts.append(
            f"Position size: {position_size.size_pct:.2%} "
            f"(method: {position_size.method})."
        )
        reasoning_parts.append(
            f"Stop loss: ${stop_loss:.2f} "
            f"({self.risk_config.stop_loss_atr_multiple}x ATR), "
            f"Take profit: ${take_profit:.2f} "
            f"(R:R = {rr_ratio:.2f})."
        )

        return TradeRecommendation(
            symbol=symbol,
            direction=direction,
            confidence=agg.confidence,
            strategies_agreeing=agg.agreeing,
            strategies_disagreeing=agg.disagreeing,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size_pct=position_size.size_pct,
            risk_reward_ratio=rr_ratio,
            timestamp=datetime.utcnow(),
            reasoning=" ".join(reasoning_parts),
        )

    def _calculate_atr(
        self, data: pd.DataFrame, period: int = 14
    ) -> float:
        """Calculate Average True Range.

        Args:
            data: OHLCV DataFrame.
            period: ATR period.

        Returns:
            Current ATR value.
        """
        if len(data) < period + 1:
            # Fallback: use simple average range
            return float((data["high"] - data["low"]).mean())

        high = data["high"]
        low = data["low"]
        close = data["close"]

        prev_close = close.shift(1)
        tr1 = high - low
        tr2 = (high - prev_close).abs()
        tr3 = (low - prev_close).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        atr = true_range.rolling(period).mean().iloc[-1]
        return float(atr) if pd.notna(atr) else float(true_range.mean())

    def analyze(
        self,
        symbol: str,
        data: pd.DataFrame,
        portfolio_value: float = 100000.0,
        sector: Optional[str] = None,
    ) -> AnalysisResult:
        """Generate a trade recommendation for a symbol.

        This is the main entry point for single-symbol analysis.

        Pipeline:
        1. Collect signals from all active strategies
        2. Aggregate signals (weighted by performance)
        3. Check confidence threshold
        4. Check agreement threshold
        5. Calculate position size (Kelly criterion or fixed fractional)
        6. Set stop-loss and take-profit levels
        7. Run portfolio-level risk checks
        8. Generate recommendation with full reasoning

        Args:
            symbol: Asset ticker symbol.
            data: OHLCV DataFrame with enough data.
            portfolio_value: Total portfolio value for sizing.
            sector: Asset sector (auto-detected if None).

        Returns:
            AnalysisResult with recommendation or HOLD.
        """
        if sector is None:
            sector = self._determine_sector(symbol)

        # Step 1: Collect signals
        signals = self._collect_signals(data, symbol)

        # Step 2: Aggregate
        agg = aggregate_signals(signals, self.strategy_performance)
        direction = direction_from_signal(agg.direction)

        # Step 3 & 4: Check confidence and agreement
        confidence_check = agg.confidence >= self.risk_config.min_confidence
        agreement_check = (
            len(agg.agreeing) >= self.risk_config.min_strategies_agreeing
        )

        # Default recommendation is HOLD
        recommendation: Optional[TradeRecommendation] = None
        reasoning_parts: List[str] = []

        # Step 5: Position sizing
        entry_price = float(data["close"].iloc[-1])
        atr = self._calculate_atr(data)
        stop_distance_pct = (
            self.risk_config.stop_loss_atr_multiple * atr / entry_price
            if entry_price > 0
            else 0.02
        )

        # Try to get performance data for Kelly
        win_rate: Optional[float] = None
        avg_win: Optional[float] = None
        avg_loss: Optional[float] = None

        # Aggregate performance across agreeing strategies
        agreeing_perfs = [
            self.strategy_performance[sid]
            for sid in agg.agreeing
            if sid in self.strategy_performance
        ]
        if agreeing_perfs:
            win_rate = sum(p.win_rate for p in agreeing_perfs) / len(agreeing_perfs)
            avg_win = sum(p.profit_factor for p in agreeing_perfs) / len(agreeing_perfs) * 0.02
            avg_loss = 0.02  # Default 2% avg loss

        pos_size = calculate_position_size(
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            risk_config=self.risk_config,
            stop_distance_pct=stop_distance_pct,
            portfolio_value=portfolio_value,
        )

        # Step 7: Risk checks
        risk_result = run_all_risk_checks(
            size_pct=pos_size.size_pct,
            confidence=agg.confidence,
            agreeing_count=len(agg.agreeing),
            symbol=symbol,
            sector=sector,
            portfolio=self.portfolio,
            risk_config=self.risk_config,
        )

        # Step 8: Build recommendation or HOLD
        if direction == Direction.HOLD:
            reasoning_parts.append(
                "No clear directional signal — HOLD."
            )
        elif not confidence_check:
            reasoning_parts.append(
                f"Confidence {agg.confidence:.3f} below minimum "
                f"{self.risk_config.min_confidence}. HOLD."
            )
        elif not agreement_check:
            reasoning_parts.append(
                f"Only {len(agg.agreeing)} strategies agree "
                f"(min {self.risk_config.min_strategies_agreeing}). HOLD."
            )
        elif not risk_result.passed:
            reasoning_parts.append(
                f"Risk check failed: {risk_result.reason}. HOLD."
            )
        else:
            recommendation = self._build_recommendation(
                symbol, agg, direction, entry_price, pos_size, atr
            )
            reasoning_parts.append(
                f"Recommendation: {direction.value} with "
                f"{agg.confidence:.2%} confidence."
            )

        combined_reasoning = (
            " ".join(reasoning_parts)
            if reasoning_parts
            else "Analysis complete."
        )

        if recommendation:
            combined_reasoning = (
                f"{combined_reasoning} {recommendation.reasoning}"
            )

        # Build analysis result
        result = AnalysisResult(
            symbol=symbol,
            aggregated=agg,
            recommendation=recommendation,
            risk_result=risk_result,
            position_size=pos_size,
            signals=signals,
            reasoning=combined_reasoning,
        )

        # Log the decision
        log_decision(
            symbol=symbol,
            input_data={
                "portfolio_value": portfolio_value,
                "sector": sector,
                "atr": atr,
                "num_bars": len(data),
            },
            strategy_signals=[
                {
                    "strategy_id": s.strategy_id,
                    "direction": s.direction,
                    "confidence": s.confidence,
                    "reasoning": s.reasoning,
                }
                for s in signals
            ],
            aggregated_direction=agg.direction,
            aggregated_confidence=agg.confidence,
            confidence_check=confidence_check,
            agreement_check=agreement_check,
            risk_checks={
                "all_passed": risk_result.passed,
                "details": risk_result.checks,
                "reason": risk_result.reason,
            },
            recommendation=recommendation,
            reasoning=combined_reasoning,
        )

        return result

    def analyze_portfolio(
        self,
        portfolio: PortfolioState,
        market_data: Dict[str, pd.DataFrame],
        portfolio_value: float = 100000.0,
    ) -> List[AnalysisResult]:
        """Analyze all holdings and generate recommendations for rebalancing.

        Args:
            portfolio: Current portfolio state.
            market_data: Map from symbol to OHLCV DataFrame.
            portfolio_value: Total portfolio value.

        Returns:
            List of AnalysisResult for each position.
        """
        self.portfolio = portfolio
        results: List[AnalysisResult] = []

        for position in portfolio.positions:
            if position.symbol in market_data:
                result = self.analyze(
                    symbol=position.symbol,
                    data=market_data[position.symbol],
                    portfolio_value=portfolio_value,
                    sector=position.sector,
                )
                results.append(result)

        return results

    def check_risk(
        self,
        symbol: str,
        size_pct: float,
        sector: str = "unknown",
    ) -> RiskCheckResult:
        """Validate a proposed trade against risk rules.

        Args:
            symbol: Symbol to check.
            size_pct: Proposed position size.
            sector: Asset sector.

        Returns:
            RiskCheckResult indicating pass/fail.
        """
        return run_all_risk_checks(
            size_pct=size_pct,
            confidence=self.risk_config.min_confidence,  # Assume passes
            agreeing_count=self.risk_config.min_strategies_agreeing,  # Assume passes
            symbol=symbol,
            sector=sector,
            portfolio=self.portfolio,
            risk_config=self.risk_config,
        )

    def explain(self, result: AnalysisResult) -> str:
        """Generate human-readable explanation of a trade recommendation.

        Args:
            result: AnalysisResult to explain.

        Returns:
            Detailed human-readable explanation.
        """
        lines: List[str] = []
        lines.append(f"Analysis for {result.symbol}")
        lines.append(f"{'─' * 50}")

        if result.aggregated:
            agg = result.aggregated
            lines.append(f"Aggregated Direction: {agg.direction:+.3f}")
            lines.append(f"Aggregate Confidence: {agg.confidence:.3f}")
            lines.append(f"Strategies Agreeing: {len(agg.agreeing)} ({', '.join(agg.agreeing)})")
            if agg.disagreeing:
                lines.append(f"Strategies Disagreeing: {len(agg.disagreeing)} ({', '.join(agg.disagreeing)})")
            lines.append("")

        lines.append(f"Individual Signals ({len(result.signals)} strategies):")
        for sig in result.signals:
            direction_str = "BUY" if sig.direction > 0 else ("SELL" if sig.direction < 0 else "NEUTRAL")
            lines.append(
                f"  {sig.strategy_id}: {direction_str} "
                f"(conf={sig.confidence:.3f}) — {sig.reasoning}"
            )
        lines.append("")

        if result.recommendation:
            lines.append(format_recommendation(result.recommendation))
        else:
            lines.append("No trade recommendation (HOLD)")

        if result.risk_result:
            lines.append("")
            lines.append("Risk Checks:")
            for check_name, passed in result.risk_result.checks.items():
                status = "✓ PASS" if passed else "✗ FAIL"
                lines.append(f"  {check_name}: {status}")
            if not result.risk_result.passed:
                lines.append(f"  Reason: {result.risk_result.reason}")

        lines.append("")
        lines.append(f"Reasoning: {result.reasoning}")

        return "\n".join(lines)

    def simulate(
        self,
        result: AnalysisResult,
        price_change_pct: float,
    ) -> Dict[str, Any]:
        """What-if analysis: simulate the outcome of a recommendation.

        Args:
            result: AnalysisResult to simulate.
            price_change_pct: Simulated price change as fraction (e.g., 0.05 for +5%).

        Returns:
            Dictionary with simulated P&L and outcome details.
        """
        if result.recommendation is None:
            return {
                "symbol": result.symbol,
                "action": "HOLD",
                "simulated_pnl_pct": 0.0,
                "simulated_pnl_dollar": 0.0,
                "hit_stop": False,
                "hit_target": False,
                "explanation": "No position — HOLD recommendation.",
            }

        rec = result.recommendation
        entry = rec.entry_price
        current = entry * (1 + price_change_pct)

        if rec.direction == Direction.BUY:
            pnl_pct = (current - entry) / entry
        elif rec.direction == Direction.SELL:
            pnl_pct = (entry - current) / entry
        else:
            pnl_pct = 0.0

        # Check stop/target
        hit_stop = False
        hit_target = False
        if rec.direction == Direction.BUY:
            hit_stop = current <= rec.stop_loss
            hit_target = current >= rec.take_profit
        elif rec.direction == Direction.SELL:
            hit_stop = current >= rec.stop_loss
            hit_target = current <= rec.take_profit

        return {
            "symbol": result.symbol,
            "action": rec.direction.value,
            "entry_price": entry,
            "simulated_price": current,
            "simulated_pnl_pct": pnl_pct,
            "position_size_pct": rec.position_size_pct,
            "simulated_pnl_dollar": pnl_pct * rec.position_size_pct * 100000,
            "hit_stop": hit_stop,
            "hit_target": hit_target,
            "explanation": (
                f"Simulated {price_change_pct:+.1%} move on {rec.direction.value} position. "
                f"P&L: {pnl_pct:+.2%}. "
                + (
                    "Hit stop loss."
                    if hit_stop
                    else "Hit take profit." if hit_target else "Position still open."
                )
            ),
        }

    def get_logs(self, symbol: Optional[str] = None) -> List:
        """Get decision audit logs.

        Args:
            symbol: Filter by symbol.

        Returns:
            List of DecisionLog entries.
        """
        return get_decision_logs(symbol=symbol)

    def clear_logs(self) -> None:
        """Clear all decision logs."""
        clear_decision_logs()
