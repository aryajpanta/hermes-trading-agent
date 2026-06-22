"""Dividend Growth — Value strategy inspired by Peter Lynch.

Identifies companies with consistent dividend growth, reasonable payout ratio,
and attractive valuation for long-term income investing.
"""

from typing import List, Optional

import pandas as pd

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.library import register_strategy_class
from src.strategy.signals import Signal

STRATEGY_ID = "dividend_growth"


class DividendGrowthStrategy(BaseStrategy):
    """Dividend Growth strategy — value-focused income investing."""

    def __init__(self, config: Optional[Strategy] = None) -> None:
        if config is None:
            config = Strategy(
                id=STRATEGY_ID,
                name="Dividend Growth",
                source="Peter Lynch",
                description="Buy quality companies with consistent dividend growth and reasonable valuation.",
                category="value",
                timeframes=["1d", "1w", "1m"],
                assets=["stocks"],
                entry_rules=[
                    "Dividend yield > 2%",
                    "Dividend payout ratio < 60%",
                    "Consecutive dividend increases for 10+ years (Dividend Aristocrat)",
                    "P/E ratio below sector average",
                    "Debt-to-equity ratio < 1.0",
                    "Price-to-earnings growth (PEG) ratio < 1.5",
                ],
                exit_rules=[
                    "Dividend cut or freeze announced",
                    "Payout ratio exceeds 80%",
                    "Stock becomes overvalued (P/E > 30 or PEG > 3)",
                    "Better opportunities available at lower risk",
                ],
                stop_loss_pct=0.10,
                take_profit_pct=0.30,
                position_size_pct=0.10,
                max_holding_period=0,
                min_confidence=0.6,
            )
        super().__init__(config)

    def required_indicators(self) -> List[str]:
        return ["DividendYield", "PayoutRatio", "PE_Ratio", "DE_Ratio"]

    def minimum_data_points(self) -> int:
        return 50

    def evaluate(self, data: pd.DataFrame) -> Signal:
        # For a data-only strategy, we use price-based proxies
        # In production, fundamental data would be fetched separately
        close = data["close"]

        sma_50 = close.rolling(50).mean()
        sma_200 = close.rolling(200).mean() if len(close) >= 200 else close.rolling(len(close)).mean()

        current_price = close.iloc[-1]
        current_sma50 = sma_50.iloc[-1]

        # Price stability as a proxy for dividend stock behavior
        returns = close.pct_change()
        volatility_30d = returns.tail(30).std() if len(returns) >= 30 else returns.std()
        downside_vol = returns[returns < 0].tail(30).std() if len(returns[returns < 0]) >= 30 else returns.std()

        # Trend quality
        price_vs_sma50 = (current_price - current_sma50) / current_sma50 if current_sma50 > 0 else 0

        score = 0
        reasons = []

        # Low volatility suggests defensive/dividend stock
        if volatility_30d < 0.02:
            score += 2
            reasons.append("Low volatility (defensive stock)")
        elif volatility_30d < 0.03:
            score += 1
            reasons.append("Moderate volatility")

        # Steady uptrend without sharp moves
        if -0.02 < price_vs_sma50 < 0.05 and current_price > current_sma50:
            score += 1
            reasons.append("Price steadily above 50d MA")

        # Limited downside
        if downside_vol < 0.015:
            score += 1
            reasons.append("Limited downside volatility")

        if score >= 3:
            confidence = min(0.8, 0.6 + (score - 3) * 0.1)
            return self._make_signal(0.7, confidence, f"Dividend growth candidate ({score}/4): {', '.join(reasons)}. Fundamental data needed for full analysis.", metadata={"score": score})
        if score >= 2:
            return self._make_signal(0.4, 0.5, f"Possible dividend growth ({score}/4): {', '.join(reasons)}.", metadata={"score": score})

        return self._make_signal(0.0, 0.3, f"Insufficient dividend growth signals ({score}/4). Fundamental data required.", metadata={"score": score})


register_strategy_class(STRATEGY_ID, DividendGrowthStrategy)
