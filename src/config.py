"""Unified configuration for the trading system.

Single source of truth for env vars + YAML settings. Used by:
- ``src/main.py`` (startup validation)
- ``src/broker/alpaca.py`` (env override)
- ``src/automation/scheduler.py`` (intervals, enable flag)
- ``src/sentiment/gemini.py`` (API key)
- ``src/tradingview/webhook.py`` (secret)

Pydantic v2 Settings with sensible defaults that match the existing
HTA env var names for drop-in compatibility.
"""

import logging
import os
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name, "true" if default else "false").lower()
    return val in ("true", "1", "yes", "on")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# ── Settings container ─────────────────────────────────────


class Settings:
    """Lazy-evaluated settings. Read from env on each access."""

    # ── Server ──
    @property
    def port(self) -> int:
        return _env_int("PORT", 8000)

    @property
    def host(self) -> str:
        return os.environ.get("HOST", "0.0.0.0")

    @property
    def log_level(self) -> str:
        return os.environ.get("LOG_LEVEL", "INFO")

    @property
    def dev_mode(self) -> bool:
        return _env_bool("DEV", False)

    # ── Alpaca ──
    @property
    def alpaca_key(self) -> str:
        return (
            os.environ.get("ALPACA_API_KEY")
            or os.environ.get("ALPACA_API_KEY_ID")
            or ""
        )

    @property
    def alpaca_secret(self) -> str:
        return (
            os.environ.get("ALPACA_SECRET_KEY")
            or os.environ.get("ALPACA_SECRET")
            or ""
        )

    @property
    def alpaca_paper(self) -> bool:
        return _env_bool("ALPACA_PAPER", True)

    @property
    def alpaca_configured(self) -> bool:
        return bool(self.alpaca_key and self.alpaca_secret)

    # ── Gemini ──
    @property
    def gemini_api_key(self) -> str:
        return os.environ.get("GEMINI_API_KEY", "")

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)

    # ── TradingView webhook ──
    @property
    def webhook_secret(self) -> str:
        return os.environ.get("WEBHOOK_SECRET", "")

    @property
    def webhook_configured(self) -> bool:
        return bool(self.webhook_secret)

    # ── Automation ──
    @property
    def automation_enabled(self) -> bool:
        return _env_bool("ENABLE_AUTOMATION", True)

    @property
    def monitor_interval_ms(self) -> int:
        return _env_int("AUTOMATION_INTERVAL_MS", 60_000)

    @property
    def review_interval_ms(self) -> int:
        return _env_int("REVIEW_INTERVAL_MS", 86_400_000)

    @property
    def paper_balance_usd(self) -> float:
        return _env_float("PAPER_BALANCE_USD", 100_000.0)

    # ── Strategy config ──
    @property
    def strategy_config_path(self) -> str:
        return os.environ.get("STRATEGY_CONFIG_PATH", "data/strategy/config.yaml")

    # ── Paths ──
    @property
    def data_dir(self) -> Path:
        p = Path(os.environ.get("DATA_DIR", "data"))
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def paper_portfolio_path(self) -> Path:
        return self.data_dir / "paper_portfolio.json"

    # ── Validation ──

    def validate(self) -> List[str]:
        """Return a list of warnings about missing recommended config."""
        warnings: List[str] = []
        if not self.alpaca_configured:
            warnings.append(
                "ALPACA_API_KEY_ID/ALPACA_SECRET_KEY not set — broker features disabled"
            )
        if not self.gemini_configured:
            warnings.append(
                "GEMINI_API_KEY not set — sentiment analysis returns neutral"
            )
        if not self.webhook_configured:
            warnings.append(
                "WEBHOOK_SECRET not set — TradingView webhook is unauthenticated"
            )
        return warnings

    def summary(self) -> dict:
        return {
            "server": {"port": self.port, "host": self.host, "dev": self.dev_mode},
            "alpaca": {
                "configured": self.alpaca_configured,
                "paper": self.alpaca_paper,
            },
            "gemini": {"configured": self.gemini_configured},
            "webhook": {"configured": self.webhook_configured},
            "automation": {
                "enabled": self.automation_enabled,
                "monitor_interval_s": self.monitor_interval_ms / 1000,
                "review_interval_s": self.review_interval_ms / 1000,
            },
        }


# Singleton
settings = Settings()
