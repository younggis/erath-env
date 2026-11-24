"""Blitzortung / LightningMaps real-time strike cache.

Keeps a short (15-30 min) sliding window of global lightning positions with
coarse de-duplication. Network access is optional and always bounded: the
poller runs in its own daemon thread with an HTTP timeout and exponential
backoff, so an unreachable upstream never blocks the ingest loop or the API.
"""
from __future__ import annotations

import json
import logging
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..config import get_settings
from ..fields.timeutil import to_iso

log = logging.getLogger(__name__)

SOURCE_ID = "blitzortung"
API_URL = "https://api.lightningmaps.org/"
DEFAULT_WINDOW_MINUTES = 20
DEFAULT_MAX_STRIKES = 5000
DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_BACKOFF_SECONDS = 5.0

_state: dict[str, Any] = {
    "connected": False, "last_poll_at": None, "last_error": None,
    "polls": 0, "strikes_received": 0,
}


def backoff_delay(attempt: int, base: float = DEFAULT_BACKOFF_SECONDS, cap: float = 60.0) -> float:
    """Exponential backoff for a failing upstream (attempt starts at 1)."""
    return min(cap, max(0.1, float(base)) * (2 ** max(0, int(attempt) - 1)))


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> str | None:
    if value is None:
        return None
    try:
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        if seconds <= 0:
            return None
        return to_iso(datetime.fromtimestamp(seconds, tz=timezone.utc))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def parse_strike(raw: Any) -> dict | None:
    """Normalise one LightningMaps stroke (dict or positional array)."""
    if isinstance(raw, (list, tuple)):
        if len(raw) < 3:
            return None
        lon, lat, ts = _number(raw[0]), _number(raw[1]), _timestamp(raw[2])
        sid = str(raw[3]) if len(raw) > 3 and raw[3] is not None else None
        raw_dict = {}
    elif isinstance(raw, dict):
        lon = _number(raw.get("lon", raw.get("longitude", raw.get("lng"))))
        lat = _number(raw.get("lat", raw.get("latitude")))
        ts = _timestamp(raw.get("time", raw.get("timestamp", raw.get("t"))))
        sid = str(raw["id"]) if raw.get("id") is not None else None
        raw_dict = raw
    else:
        return None

    if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    observed = ts or to_iso(datetime.now(timezone.utc))
    return {
        "id": sid or f"{lon:.4f},{lat:.4f},{observed}",
        "lon": lon, "lat": lat, "observed_at": observed,
        "source_id": SOURCE_ID,
        "magnitude": _number(raw_dict.get("magnitude", raw_dict.get("power"))) if raw_dict else None,
    }


def extract_strikes(payload: Any) -> list[Any]:
    """Pull the stroke list out of the LightningMaps envelope."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("strokes", "strikes", "lightning", "data", "d", "l"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


class LightningCache:
    """Thread-safe time-windowed strike store with MMSI-style de-duplication."""

    def __init__(self, window_minutes: int = DEFAULT_WINDOW_MINUTES,
                 max_strikes: int = DEFAULT_MAX_STRIKES):
        self.window = timedelta(minutes=max(1, int(window_minutes)))
        self.max_strikes = max(1, int(max_strikes))
        self._strikes: dict[str, dict] = {}
        self._lock = threading.Lock()

    def ingest(self, raw_items: Any) -> int:
        added = 0
        for raw in extract_strikes(raw_items):
            strike = parse_strike(raw)
            if not strike:
                continue
            with self._lock:
                self._strikes[strike["id"]] = strike
                added += 1
        self.prune()
        _state["strikes_received"] += added
        return added

    def prune(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        cutoff = now - self.window
        with self._lock:
            expired = [key for key, value in self._strikes.items()
                       if _as_time(value["observed_at"]) < cutoff]
            for key in expired:
                self._strikes.pop(key, None)
            if len(self._strikes) > self.max_strikes:
                keep = sorted(self._strikes.values(),
                              key=lambda s: s["observed_at"], reverse=True)[:self.max_strikes]
                self._strikes = {s["id"]: s for s in keep}
            return len(expired)

    def snapshot(self, limit: int = 5000) -> list[dict]:
        with self._lock:
            rows = sorted(self._strikes.values(),
                          key=lambda s: s["observed_at"], reverse=True)
        return rows[:max(0, int(limit))]

    def size(self) -> int:
        with self._lock:
            return len(self._strikes)

    def clear(self) -> None:
        with self._lock:
            self._strikes.clear()


def _as_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, AttributeError):
        return datetime.now(timezone.utc)


_CACHE = LightningCache()


def fetch_strikes(fetcher: Callable[[str, float], Any] | None = None,
                  timeout: float = DEFAULT_TIMEOUT_SECONDS) -> list[Any]:
    """Fetch and decode one payload. Raises IngestError on any upstream fault."""
    from .base import IngestError
    if fetcher is None:
        import httpx
        def fetcher(url, t):
            with httpx.Client(timeout=t, follow_redirects=True) as client:
                response = client.get(url)
                response.raise_for_status()
                return response.text
    try:
        payload = fetcher(API_URL, timeout)
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        return extract_strikes(payload)
    except Exception as e:  # noqa: BLE001
        raise IngestError("UPSTREAM_ERROR", f"闪电数据源不可用：{e}") from e


def safe_poll(fetcher: Callable[[str, float], Any] | None = None,
              attempt: int = 1) -> dict:
    """One non-throwing poll with bounded timeout info and backoff hint."""
    _state["polls"] += 1
    try:
        strikes = fetch_strikes(fetcher)
        count = _CACHE.ingest(strikes)
        _state["last_poll_at"] = to_iso(datetime.now(timezone.utc))
        _state["last_error"] = None
        _state["connected"] = True
        return {"ok": True, "received": count, "cached": _CACHE.size()}
    except Exception as e:  # noqa: BLE001
        _state["connected"] = False
        _state["last_error"] = str(e)[:200]
        return {"ok": False, "error": str(e)[:200],
                "retry_after_seconds": backoff_delay(attempt)}


_poll_thread: threading.Thread | None = None
_poll_stop = threading.Event()


def poller_loop(interval: float = 30.0) -> None:
    """Run in a daemon thread: bounded polls, backoff on failure, never blocks callers."""
    failures = 0
    while not _poll_stop.is_set():
        result = safe_poll(attempt=failures + 1)
        if result.get("ok"):
            failures = 0
            wait = max(1.0, float(interval))
        else:
            failures += 1
            wait = float(result.get("retry_after_seconds", backoff_delay(failures)))
        _poll_stop.wait(wait)


def start_poller(interval: float | None = None) -> bool:
    global _poll_thread
    if _poll_thread and _poll_thread.is_alive():
        return False
    seconds = interval or get_settings().lightning_poll_seconds
    _poll_stop.clear()

    def runner() -> None:
        try:
            poller_loop(seconds)
        except Exception as e:  # noqa: BLE001
            log.warning("lightning poller stopped: %s", e)

    _poll_thread = threading.Thread(target=runner, name="lightning-poll", daemon=True)
    _poll_thread.start()
    return True


def stop_poller() -> None:
    _poll_stop.set()


def status(limit: int = 5000) -> dict:
    s = get_settings()
    strikes = _CACHE.snapshot(limit)
    return {
        "enabled": True,
        "count": len(strikes),
        "strikes": strikes,
        "last_poll_at": _state["last_poll_at"],
        "last_error": _state["last_error"],
        "polls": _state["polls"],
        "received": _state["strikes_received"],
        "window_minutes": s.lightning_window_minutes if hasattr(s, "lightning_window_minutes") else DEFAULT_WINDOW_MINUTES,
        "note": "Blitzortung/LightningMaps 社区闪电定位（超时退避，异常不阻塞主循环）",
        "source_url": API_URL,
    }
