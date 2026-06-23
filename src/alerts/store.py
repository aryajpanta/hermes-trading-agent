"""Persistent JSON store for alerts.

A simple thread-safe JSON file store. Alerts are stored as a list of
dictionaries in ``data/alerts.json``. Reads return a deep copy so
callers can mutate without affecting the store.
"""

import json
import logging
import os
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/alerts.json")


class AlertStore:
    """Thread-safe JSON-backed alert store."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or DEFAULT_PATH
        self._lock = threading.Lock()

    # ── I/O ────────────────────────────────────────────

    def _ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._atomic_write([])

    def _atomic_write(self, data: List[Dict[str, Any]]) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp, self.path)

    def _read(self) -> List[Dict[str, Any]]:
        self._ensure()
        try:
            with open(self.path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"AlertStore read failed: {e}")
            return []

    # ── CRUD ───────────────────────────────────────────

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            return deepcopy(self._read())

    def get(self, alert_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            for a in self._read():
                if a.get("id") == alert_id:
                    return deepcopy(a)
        return None

    def add(
        self,
        symbol: str,
        asset_class: str,
        condition: str,
        value: float,
        action: str,
        message: str = "",
        repeatable: bool = False,
    ) -> Dict[str, Any]:
        alert = {
            "id": f"alert_{uuid.uuid4().hex[:8]}",
            "symbol": symbol.upper(),
            "assetClass": asset_class.lower(),
            "condition": condition,
            "value": float(value),
            "action": action.lower(),
            "message": message,
            "repeatable": bool(repeatable),
            "triggered": False,
            "lastTriggeredAt": None,
            "createdAt": datetime.utcnow().isoformat() + "Z",
        }
        with self._lock:
            alerts = self._read()
            alerts.append(alert)
            self._atomic_write(alerts)
        return alert

    def remove(self, alert_id: str) -> bool:
        with self._lock:
            alerts = self._read()
            new_alerts = [a for a in alerts if a.get("id") != alert_id]
            if len(new_alerts) == len(alerts):
                return False
            self._atomic_write(new_alerts)
        return True

    def reset_all(self) -> int:
        """Reset triggered flags on all alerts (for re-arming)."""
        with self._lock:
            alerts = self._read()
            count = 0
            for a in alerts:
                if a.get("triggered"):
                    a["triggered"] = False
                    count += 1
            self._atomic_write(alerts)
        return count

    def mark_triggered(self, alert_id: str) -> None:
        with self._lock:
            alerts = self._read()
            for a in alerts:
                if a.get("id") == alert_id:
                    a["triggered"] = True
                    a["lastTriggeredAt"] = datetime.utcnow().isoformat() + "Z"
            self._atomic_write(alerts)
