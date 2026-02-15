# SE_SHEETSAI — BI query/pivot cache (in-memory TTL).
"""
Simple in-memory cache for /bi/query and /bi/pivot.
Key = hash(dash_id, widget_id, filters, role).
TTL from BI_CACHE_TTL.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any, Dict, Optional

try:
    from config import BI_CACHE_TTL
except ImportError:
    BI_CACHE_TTL = 45

_store: Dict[str, Dict[str, Any]] = {}


def _make_key(dash_id: str, widget_id: str, filters: Any, role: Optional[str] = None) -> str:
    raw = json.dumps({"d": dash_id, "w": widget_id, "f": filters, "r": role or ""}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def get(dash_id: str, widget_id: str, filters: Any, role: Optional[str] = None) -> Optional[Dict[str, Any]]:
    key = _make_key(dash_id, widget_id, filters, role)
    entry = _store.get(key)
    if not entry:
        return None
    ts = entry.get("timestamp") or 0
    if BI_CACHE_TTL > 0 and (time.time() - ts) > BI_CACHE_TTL:
        del _store[key]
        return None
    return entry.get("data")


def set_(dash_id: str, widget_id: str, filters: Any, data: Dict[str, Any], role: Optional[str] = None) -> None:
    key = _make_key(dash_id, widget_id, filters, role)
    _store[key] = {"data": data, "timestamp": time.time()}


def clear() -> None:
    _store.clear()
