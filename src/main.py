"""Unified Trading Intelligence System — production entry point.

Single FastAPI app that combines:
- TI dashboard (Jinja2 + Alpine.js frontend)
- TI REST API (overview, markets, strategies, signals, trades, sentiment)
- HTA-compatible REST API (status, portfolio, tick, alerts, review, optimize)
- TradingView webhook receiver
- Background automation scheduler (tick loop + review cycle)
- Alpaca broker proxy

Run:
    python -m src.main                # development
    uvicorn src.main:app --port 8000  # production
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Ensure project root is on path
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI

# Configure logging
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("unified")

# Lazy scheduler reference (set during lifespan)
_scheduler = None


def get_scheduler_status() -> dict:
    """Return the current scheduler status (called from API)."""
    if _scheduler is None:
        return {"enabled": False, "error": "scheduler_not_initialized"}
    return _scheduler.status


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage app startup/shutdown — start the automation scheduler + learning orchestrator."""
    global _scheduler

    from src.automation.scheduler import AutomationScheduler
    from src.learning.orchestrator import LearningOrchestrator
    from src.learning.integration import set_orchestrator, is_learning_enabled

    _scheduler = AutomationScheduler()
    await _scheduler.start()

    # Attach the learning orchestrator. Disabled with LEARNER_DISABLED=1.
    if not is_learning_enabled():
        try:
            orch = LearningOrchestrator(
                retrain_every_n=int(os.environ.get("LEARNER_RETRAIN_EVERY_N", 5)),
                data_dir=os.environ.get("LEARNER_DATA_DIR", "data/learning"),
                min_trades_for_retrain=int(
                    os.environ.get("LEARNER_MIN_TRADES", 20)
                ),
            )
            set_orchestrator(orch)
            logger.info(
                "[main] learning orchestrator attached (min_trades=%d, retrain_every_n=%d)",
                orch.min_trades, orch.scheduler.retrain_every_n,
            )
        except Exception as e:
            logger.warning("[main] learning orchestrator failed to attach: %s", e)
    else:
        logger.info("[main] learning disabled (LEARNER_DISABLED=1)")

    logger.info("[main] startup complete — unified trading system live")
    try:
        yield
    finally:
        logger.info("[main] shutting down...")
        if _scheduler:
            await _scheduler.stop()
        logger.info("[main] shutdown complete")


# Create the app
app = FastAPI(
    title="Unified Trading Intelligence",
    description=(
        "Single-service replacement for trading-intelligence + hermes-trading-agent. "
        "Combines 15-strategy library, sentiment, paper trading, continuous tick loop, "
        "self-improve review, and TradingView webhook."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── Health check (HTA-compatible) ──────────────────────────


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {
        "status": "ok",
        "service": "unified-trading-intelligence",
        "version": app.version,
    }


# ── Learning endpoints (orchestrator status + features) ──


@app.get("/api/learning/status", tags=["learning"])
async def learning_status() -> dict:
    """Return current learning orchestrator status (model state, weights, etc)."""
    from src.learning.integration import get_orchestrator
    orch = get_orchestrator()
    if orch is None:
        return {
            "enabled": False,
            "reason": "no orchestrator attached (LEARNER_DISABLED=1 or startup error)",
        }
    return {"enabled": True, **orch.status()}


@app.get("/api/learning/features", tags=["learning"])
async def learning_features() -> dict:
    """Return the feature schema and current model feature importances."""
    from src.learning.features.schema import FEATURE_COLUMNS, LABEL_COLUMN
    from src.learning.integration import get_orchestrator
    orch = get_orchestrator()
    importance = orch.learner.feature_importance() if orch is not None else {}
    sorted_imp = dict(
        sorted(importance.items(), key=lambda x: x[1], reverse=True)
    )
    return {
        "feature_columns": FEATURE_COLUMNS,
        "label_column": LABEL_COLUMN,
        "feature_importance": sorted_imp,
    }


@app.get("/api/learning/gate-log", tags=["learning"])
async def learning_gate_log(limit: int = 20) -> dict:
    """Return recent validation gate decisions (most recent first)."""
    import json
    from pathlib import Path
    log_path = Path("data/learning/gate_log.jsonl")
    if not log_path.exists():
        return {"decisions": []}
    with open(log_path) as f:
        lines = f.readlines()
    recent = [json.loads(l) for l in lines[-limit:]][::-1]
    return {"decisions": recent}


# ── Mount routers ──────────────────────────────────────────


def _mount_routers() -> None:
    """Mount all API routers. Imports are lazy to keep startup fast."""
    from src.dashboard.api import router as ti_api
    from src.dashboard.routes import router as ti_pages
    from src.dashboard.unified import router as hta_api, webhooks as hta_webhooks

    # Static + pages
    static_dir = Path(__file__).parent / "dashboard" / "static"
    if static_dir.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(ti_pages)
    app.include_router(ti_api)
    app.include_router(hta_api)

    # Webhooks at /webhook/tradingview (HTA-compatible path)
    from src.tradingview.webhook import router as tv_router

    app.include_router(tv_router)

    # TradingView setup info endpoint (root level)
    @app.get("/api/tradingview/setup", tags=["setup"])
    async def tradingview_setup() -> dict:
        return {
            "url": "<your-service-url>/webhook/tradingview",
            "method": "POST",
            "content_type": "application/json",
            "secret_env": "WEBHOOK_SECRET (set on Railway)",
            "example_payload": {
                "secret": "<your-shared-secret>",
                "symbol": "BTCUSDT",
                "assetClass": "crypto",
                "action": "buy",
                "price": "{{close}}",
                "qty": 0.01,
                "strategy": "rsi_oversold",
                "message": "Alert from TradingView: {{time}}",
            },
            "tradingview_setup_steps": [
                "1. Open TradingView, click Alerts → Create Alert",
                "2. Set condition (indicator crossing, price level, etc.)",
                "3. In 'Webhook URL', paste your service URL + /webhook/tradingview",
                "4. In 'Message', paste the example JSON above (customize as needed)",
                "5. Click Create — alerts will fire on every trigger",
            ],
        }


_mount_routers()


# CLI entry point
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(
        "src.main:app",
        host=os.environ.get("HOST", "0.0.0.0"),
        port=port,
        reload=os.environ.get("DEV", "false").lower() == "true",
        log_level="info",
    )
