"""Page routes — serve Jinja2 HTML templates for each dashboard section."""

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])

_TEMPLATE_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


def _ctx(request: Request, **extra: Any) -> dict[str, Any]:
    """Build common template context."""
    return {"request": request, **extra}


@router.get("/", response_class=HTMLResponse)
async def overview(request: Request) -> Any:
    """Dashboard overview page."""
    return templates.TemplateResponse(request, "overview.html", _ctx(request, page="overview"))


@router.get("/markets", response_class=HTMLResponse)
async def markets_page(request: Request) -> Any:
    """Markets detail page."""
    return templates.TemplateResponse(request, "markets.html", _ctx(request, page="markets"))


@router.get("/strategies", response_class=HTMLResponse)
async def strategies_page(request: Request) -> Any:
    """Strategies page."""
    return templates.TemplateResponse(request, "strategies.html", _ctx(request, page="strategies"))


@router.get("/sentiment", response_class=HTMLResponse)
async def sentiment_page(request: Request) -> Any:
    """Sentiment analysis page."""
    return templates.TemplateResponse(request, "sentiment.html", _ctx(request, page="sentiment"))


@router.get("/trades", response_class=HTMLResponse)
async def trades_page(request: Request) -> Any:
    """Trade history page."""
    return templates.TemplateResponse(request, "trades.html", _ctx(request, page="trades"))


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request) -> Any:
    """Settings page."""
    return templates.TemplateResponse(request, "settings.html", _ctx(request, page="settings"))


@router.get("/learning", response_class=HTMLResponse)
async def learning_page(request: Request) -> Any:
    """Learning page — model status, feature importances, gate decisions."""
    return templates.TemplateResponse(request, "learning.html", _ctx(request, page="learning"))
