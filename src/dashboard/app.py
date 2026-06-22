"""FastAPI application factory for the Analysis Dashboard."""

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Directories relative to this file
_TEMPLATE_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    """Build and configure the FastAPI app.

    Returns:
        Configured FastAPI instance with routes, static files, and templates.
    """
    app = FastAPI(
        title="Trading Intelligence Dashboard",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Mount static files
    _STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Import and register routes (page routes and API routes)
    from src.dashboard.routes import router as page_router  # noqa: E402
    from src.dashboard.api import router as api_router  # noqa: E402

    app.include_router(page_router)
    app.include_router(api_router)

    return app
