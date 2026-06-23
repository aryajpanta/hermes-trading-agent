"""TradingView webhook tests.

Run: pytest tests/test_tradingview_webhook.py -v
"""

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def client():
    """Create a minimal FastAPI app for testing the webhook."""
    from fastapi import FastAPI
    from src.tradingview.webhook import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_valid_buy_alert(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post(
        "/webhook/tradingview",
        json={
            "symbol": "BTCUSDT",
            "assetClass": "crypto",
            "action": "buy",
            "price": 50000,
            "qty": 0.01,
            "strategy": "rsi_oversold",
            "message": "RSI crossed 30",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["received"] is True
    assert data["alert"]["symbol"] == "BTCUSDT"
    assert data["alert"]["action"] == "buy"


def test_valid_sell_alert(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post(
        "/webhook/tradingview",
        json={"symbol": "AAPL", "assetClass": "stock", "action": "sell", "price": 200},
    )
    assert r.status_code == 200


def test_alert_action_just_logs(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post(
        "/webhook/tradingview",
        json={"symbol": "ETHUSDT", "action": "alert", "message": "price alert"},
    )
    assert r.status_code == 200


def test_missing_symbol_400(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post("/webhook/tradingview", json={"action": "buy", "price": 100})
    assert r.status_code == 400


def test_invalid_action_400(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post(
        "/webhook/tradingview",
        json={"symbol": "BTC", "action": "moon", "price": 100},
    )
    assert r.status_code == 400


def test_invalid_json_400(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    r = client.post(
        "/webhook/tradingview",
        content="not json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400


def test_secret_required_when_set(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WEBHOOK_SECRET", "supersecret")
    r = client.post(
        "/webhook/tradingview",
        json={"symbol": "BTC", "action": "buy", "price": 100},
    )
    assert r.status_code == 401


def test_secret_accepted(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("WEBHOOK_SECRET", "supersecret")
    r = client.post(
        "/webhook/tradingview",
        json={"symbol": "BTC", "action": "buy", "price": 100, "secret": "supersecret"},
    )
    assert r.status_code == 200


def test_persistence_creates_log_file(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client.post(
        "/webhook/tradingview",
        json={"symbol": "BTC", "action": "alert", "message": "test"},
    )
    log_path = tmp_path / "data" / "webhook_alerts.json"
    assert log_path.exists()
    alerts = json.loads(log_path.read_text())
    assert len(alerts) == 1
    assert alerts[0]["symbol"] == "BTC"
