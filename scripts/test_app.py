"""Manual end-to-end test of the unified app via TestClient.

Run: python scripts/test_app.py
"""
import os
os.environ["ENABLE_AUTOMATION"] = "false"
os.environ["ENABLE_AUTOMATION"] = "false"

from fastapi.testclient import TestClient
from src.main import app

with TestClient(app) as client:
    paths = [
        ("GET", "/health"),
        ("GET", "/api/status"),
        ("GET", "/api/portfolio"),
        ("GET", "/api/cycles"),
        ("GET", "/api/strategy"),
        ("GET", "/api/automation/status"),
        ("GET", "/api/alerts"),
        ("GET", "/api/optimize/propose"),
        ("GET", "/api/tradingview/setup"),
        ("GET", "/"),
        ("POST", "/webhook/tradingview"),
    ]
    for method, path in paths:
        if method == "POST":
            r = client.post(path, json={"symbol": "BTC", "action": "alert", "message": "smoke test"})
        else:
            r = client.get(path)
        body = r.text[:80] if r.text else ""
        print(f"{method:5s} {path:35s} {r.status_code}  {body}")
