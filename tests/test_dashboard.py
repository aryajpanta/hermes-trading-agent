"""Tests for the Analysis Dashboard (M5).

Covers:
- FastAPI app creation and mounting
- Page routes (HTML responses)
- API endpoints (JSON responses)
- Data service layer (mocked)
- Template rendering
"""

import os
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Ensure test environment
os.environ.setdefault("ALPHA_VANTAGE_API_KEY", "")

from fastapi.testclient import TestClient

from src.dashboard.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client() -> TestClient:
    """Create a TestClient for the dashboard app."""
    app = create_app()
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# App Creation Tests
# ---------------------------------------------------------------------------

class TestAppCreation:
    """Tests for FastAPI app creation."""

    def test_create_app_returns_fastapi(self) -> None:
        """App factory should return a FastAPI instance."""
        from fastapi import FastAPI
        app = create_app()
        assert isinstance(app, FastAPI)

    def test_app_has_title(self) -> None:
        """App should have the correct title."""
        app = create_app()
        assert "Trading Intelligence" in app.title

    def test_app_has_docs(self) -> None:
        """App should expose docs endpoint."""
        app = create_app()
        assert app.docs_url == "/docs"


# ---------------------------------------------------------------------------
# Page Route Tests
# ---------------------------------------------------------------------------

class TestPageRoutes:
    """Tests for HTML page routes."""

    def test_overview_returns_200(self, client: TestClient) -> None:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "Trading Intelligence" in resp.text

    def test_overview_contains_nav(self, client: TestClient) -> None:
        resp = client.get("/")
        assert "Overview" in resp.text
        assert "Markets" in resp.text
        assert "Strategies" in resp.text

    def test_markets_returns_200(self, client: TestClient) -> None:
        resp = client.get("/markets")
        assert resp.status_code == 200
        assert "Markets" in resp.text

    def test_strategies_returns_200(self, client: TestClient) -> None:
        resp = client.get("/strategies")
        assert resp.status_code == 200
        assert "Strategies" in resp.text

    def test_sentiment_returns_200(self, client: TestClient) -> None:
        resp = client.get("/sentiment")
        assert resp.status_code == 200
        assert "Sentiment" in resp.text

    def test_trades_returns_200(self, client: TestClient) -> None:
        resp = client.get("/trades")
        assert resp.status_code == 200
        assert "Trades" in resp.text

    def test_settings_returns_200(self, client: TestClient) -> None:
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "Settings" in resp.text

    def test_overview_has_dark_mode_class(self, client: TestClient) -> None:
        """Body should default to dark mode."""
        resp = client.get("/")
        assert 'class="dark"' in resp.text


# ---------------------------------------------------------------------------
# API Endpoint Tests
# ---------------------------------------------------------------------------

class TestAPIEndpoints:
    """Tests for JSON API endpoints."""

    def test_api_overview(self, client: TestClient) -> None:
        resp = client.get("/api/overview")
        assert resp.status_code == 200
        data = resp.json()
        assert "market_summary" in data
        assert "tracked_symbols" in data
        assert "generated_at" in data

    def test_api_overview_structure(self, client: TestClient) -> None:
        resp = client.get("/api/overview")
        data = resp.json()
        assert isinstance(data["market_summary"], list)
        assert isinstance(data["tracked_symbols"], int)
        assert isinstance(data["active_strategies"], int)
        assert isinstance(data["active_signals"], dict)

    def test_api_strategies(self, client: TestClient) -> None:
        resp = client.get("/api/strategies")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_api_signals(self, client: TestClient) -> None:
        resp = client.get("/api/signals")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_api_trades(self, client: TestClient) -> None:
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_api_markets_spy(self, client: TestClient) -> None:
        resp = client.get("/api/markets/SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data
        assert data["symbol"] == "SPY"
        assert "history" in data
        assert isinstance(data["history"], list)

    def test_api_markets_with_days(self, client: TestClient) -> None:
        resp = client.get("/api/markets/AAPL?days=30")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "AAPL"

    def test_api_sentiment(self, client: TestClient) -> None:
        resp = client.get("/api/sentiment/SPY")
        assert resp.status_code == 200
        data = resp.json()
        assert "symbol" in data
        assert "aggregate" in data
        assert "signals" in data
        assert data["symbol"] == "SPY"

    def test_api_sentiment_with_hours(self, client: TestClient) -> None:
        resp = client.get("/api/sentiment/BTC?hours=48")
        assert resp.status_code == 200
        data = resp.json()
        assert data["symbol"] == "BTC"

    def test_api_settings_get(self, client: TestClient) -> None:
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "auto_refresh_seconds" in data
        assert "dark_mode" in data
        assert "watchlist" in data

    def test_api_settings_put(self, client: TestClient) -> None:
        resp = client.put(
            "/api/settings",
            json={"auto_refresh_seconds": 120},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["auto_refresh_seconds"] == 120


# ---------------------------------------------------------------------------
# Data Service Tests (unit)
# ---------------------------------------------------------------------------

class TestDataService:
    """Tests for the data service layer (with mocked backends)."""

    def test_get_overview_empty(self) -> None:
        """get_overview should return valid structure even with no data."""
        with patch("src.dashboard.data_service._get_market_collector") as mock_col:
            mock_inst = MagicMock()
            mock_inst.get_latest.return_value = None
            mock_inst.list_symbols.return_value = []
            mock_col.return_value = mock_inst

            with patch("src.dashboard.data_service._get_active_strategy_count", return_value=0):
                with patch("src.dashboard.data_service._get_active_signals_summary", return_value={"total": 0, "buy": 0, "sell": 0, "neutral": 0}):
                    with patch("src.dashboard.data_service._get_recent_trades", return_value=[]):
                        from src.dashboard.data_service import get_overview
                        result = get_overview()
                        assert "market_summary" in result
                        assert "generated_at" in result

    def test_get_settings_returns_dict(self) -> None:
        from src.dashboard.data_service import get_settings
        result = get_settings()
        assert isinstance(result, dict)
        assert "auto_refresh_seconds" in result

    def test_update_settings_merges(self) -> None:
        from src.dashboard.data_service import update_settings
        result = update_settings({"auto_refresh_seconds": 999})
        assert result["auto_refresh_seconds"] == 999
        # Restore default
        update_settings({"auto_refresh_seconds": 60})

    def test_get_trades_empty(self) -> None:
        from src.dashboard.data_service import get_trades
        # Trades list starts empty
        result = get_trades()
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Template Rendering Tests
# ---------------------------------------------------------------------------

class TestTemplates:
    """Verify templates render without errors."""

    @pytest.mark.parametrize("path", [
        "/",
        "/markets",
        "/strategies",
        "/sentiment",
        "/trades",
        "/settings",
    ])
    def test_template_renders(self, client: TestClient, path: str) -> None:
        resp = client.get(path)
        assert resp.status_code == 200
        assert len(resp.text) > 100  # Not empty

    def test_overview_loads_chartjs(self, client: TestClient) -> None:
        """Overview should include Chart.js for rendering charts."""
        resp = client.get("/")
        assert "chart.js" in resp.text.lower() or "chart.umd.min.js" in resp.text

    def test_overload_loads_alpine(self, client: TestClient) -> None:
        """Pages should include Alpine.js."""
        resp = client.get("/")
        assert "alpinejs" in resp.text.lower() or "alpine" in resp.text.lower()
