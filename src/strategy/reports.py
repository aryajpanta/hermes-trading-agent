"""Report generation for backtesting results.

Produces Markdown and HTML reports summarising strategy performance,
trade distributions, and equity curve images.
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from src.strategy.backtester import BacktestResult, Trade


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def generate_markdown_report(
    results: List[BacktestResult],
    output_path: Optional[str] = None,
    title: str = "Backtesting Report",
) -> str:
    """Return Markdown text and optionally write it to *output_path*."""
    lines: List[str] = []
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"# {title}")
    lines.append(f"\n*Generated: {ts}*\n")

    # ---- Summary table ----
    lines.append("## Strategy Comparison\n")
    lines.append(
        "| Strategy | Symbol | Period | Return | Annualised | Sharpe | Sortino | Max DD | Win% | PF | Trades |"
    )
    lines.append(
        "|----------|--------|--------|--------|------------|--------|---------|--------|------|-----|--------|"
    )
    for r in results:
        lines.append(
            f"| {r.strategy_id} | {r.symbol} | {r.period} "
            f"| {r.total_return:.2%} | {r.annualized_return:.2%} "
            f"| {r.sharpe_ratio:.2f} | {r.sortino_ratio:.2f} "
            f"| {r.max_drawdown:.2%} | {r.win_rate:.1%} "
            f"| {r.profit_factor:.2f} | {r.total_trades} |"
        )

    # ---- Per-strategy detail ----
    for r in results:
        lines.append(f"\n## {r.strategy_id} — {r.symbol}\n")
        lines.append(f"- **Period**: {r.period}")
        lines.append(f"- **Total Return**: {r.total_return:.2%}")
        lines.append(f"- **Annualised Return**: {r.annualized_return:.2%}")
        lines.append(f"- **Sharpe Ratio**: {r.sharpe_ratio:.2f}")
        lines.append(f"- **Sortino Ratio**: {r.sortino_ratio:.2f}")
        lines.append(f"- **Max Drawdown**: {r.max_drawdown:.2%}")
        lines.append(f"- **Win Rate**: {r.win_rate:.1%}")
        lines.append(f"- **Profit Factor**: {r.profit_factor:.2f}")
        lines.append(f"- **Total Trades**: {r.total_trades}")
        lines.append(f"- **Avg Holding Period**: {r.avg_holding_period:.1f} days")
        lines.append(f"- **Equity Curve**: `{r.strategy_id}_{r.symbol}_equity.png`")

        if r.trade_log:
            lines.append("\n### Trade Log (first 20)\n")
            lines.append("| Entry | Exit | Dir | Entry$ | Exit$ | PnL | Days |")
            lines.append("|-------|------|-----|--------|-------|-----|------|")
            for t in r.trade_log[:20]:
                d = "LONG" if t.direction > 0 else "SHORT"
                lines.append(
                    f"| {t.entry_date:%Y-%m-%d} | {t.exit_date:%Y-%m-%d} "
                    f"| {d} | {t.entry_price:.2f} | {t.exit_price:.2f} "
                    f"| {t.pnl:.2f} | {t.holding_period_days} |"
                )

    text = "\n".join(lines) + "\n"
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(text, encoding="utf-8")
    return text


# ---------------------------------------------------------------------------
# HTML report
# ---------------------------------------------------------------------------

def generate_html_report(
    results: List[BacktestResult],
    output_path: Optional[str] = None,
    title: str = "Backtesting Report",
) -> str:
    """Return an HTML string and optionally write it to *output_path*."""
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    comparison = _build_comparison_html(results)
    details = "\n".join(_build_strategy_detail_html(r) for r in results)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
       max-width: 1100px; margin: 2rem auto; padding: 0 1rem; color: #222; }}
h1 {{ border-bottom: 2px solid #2196F3; padding-bottom: 0.3rem; }}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0; }}
th, td {{ border: 1px solid #ddd; padding: 0.45rem 0.7rem; text-align: right; }}
th {{ background: #f5f7fa; }}
.positive {{ color: #2e7d32; }}
.negative {{ color: #c62828; }}
.card {{ background: #fafafa; border: 1px solid #e0e0e0; border-radius: 8px;
         padding: 1.2rem; margin: 1.5rem 0; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p><em>Generated: {ts}</em></p>
<h2>Strategy Comparison</h2>
{comparison}
{details}
</body>
</html>"""

    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(html, encoding="utf-8")
    return html


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_comparison_html(results: List[BacktestResult]) -> str:
    cols = [
        "strategy_id", "symbol", "period", "total_return", "annualized_return",
        "sharpe_ratio", "sortino_ratio", "max_drawdown", "win_rate",
        "profit_factor", "total_trades",
    ]
    headers = [
        "Strategy", "Symbol", "Period", "Return", "Ann. Return",
        "Sharpe", "Sortino", "Max DD", "Win%", "PF", "Trades",
    ]
    rows = []
    for r in results:
        d = r.summary_dict()
        cells = []
        for c in cols:
            v = d[c]
            if isinstance(v, float) and c in ("total_return", "annualized_return", "max_drawdown", "win_rate"):
                cls = "positive" if v > 0 else "negative"
                cells.append(f'<td class="{cls}">{v:.2%}</td>')
            elif isinstance(v, float):
                cells.append(f"<td>{v:.2f}</td>")
            else:
                cells.append(f"<td>{v}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")

    return (
        "<table><thead><tr>"
        + "".join(f"<th>{h}</th>" for h in headers)
        + "</tr></thead><tbody>"
        + "\n".join(rows)
        + "</tbody></table>"
    )


def _build_strategy_detail_html(r: BacktestResult) -> str:
    equity_img = f"reports/{r.strategy_id}_{r.symbol}_equity.png"
    lines = [
        f'<div class="card">',
        f"<h3>{r.strategy_id} — {r.symbol}</h3>",
        f"<p>Period: {r.period}</p>",
        f"<ul>",
        f"<li><strong>Total Return:</strong> {r.total_return:.2%}</li>",
        f"<li><strong>Sharpe Ratio:</strong> {r.sharpe_ratio:.2f}</li>",
        f"<li><strong>Sortino Ratio:</strong> {r.sortino_ratio:.2f}</li>",
        f"<li><strong>Max Drawdown:</strong> {r.max_drawdown:.2%}</li>",
        f"<li><strong>Win Rate:</strong> {r.win_rate:.1%}</li>",
        f"<li><strong>Profit Factor:</strong> {r.profit_factor:.2f}</li>",
        f"<li><strong>Total Trades:</strong> {r.total_trades}</li>",
        f"</ul>",
        f'<img src="{equity_img}" alt="Equity Curve" style="max-width:100%;">',
        f"</div>",
    ]
    return "\n".join(lines)
