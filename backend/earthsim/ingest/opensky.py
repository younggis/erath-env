"""OpenSky Network ADS-B adapter with 429-aware backoff.

Preserves SI barometric altitude, true track and vertical rate from state
vectors so the renderer can place aircraft in a real 3D altitude shell.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "opensky"
API_URL = "https://opensky-network.org/api/states/all"
DEFAULT_ATTEMPTS = 4
DEFAULT_BASE_DELAY = 2.0


def retry_delay(attempt: int, retry_after: float | None = None,
                base: float = DEFAULT_BASE_DELAY) -> float:
    backoff = min(60.0, max(0.1, base) * (2 ** max(0, attempt - 1)))
    if retry_after is not None:
        return min(60.0, max(backoff, float(retry_after)))
    return backoff


def _default_fetch(url: str) -> dict:
    import httpx
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        r = client.get(url)
        body = None
        try:
            body = r.json()
        except ValueError:
            pass
        return {"status_code": r.status_code, "body": body,
                "retry_after": r.headers.get("Retry-After")}


def fetch_states(fetcher: Callable[[str], dict] | None = None,
                 attempts: int | None = None) -> dict:
    fn = fetcher or _default_fetch
    tries = attempts or get_settings().opensky_max_attempts
    for attempt in range(1, tries + 1):
        result = fn(API_URL) or {}
        status = int(result.get("status_code", 200))
        if status == 429 or status >= 500:
            if attempt == tries:
                raise IngestError("SOURCE_THROTTLED" if status == 429 else "SOURCE_ERROR",
                                  f"OpenSky 上游返回 {status}")
            delay = retry_delay(attempt, result.get("retry_after"))
            log.warning("OpenSky %s, retry %s/%s in %.1fs", status, attempt, tries, delay)
            time.sleep(delay)
            continue
        if status >= 400:
            raise IngestError("SOURCE_ERROR", f"OpenSky 上游返回 {status}")
        return result.get("body") or {}
    raise IngestError("SOURCE_THROTTLED", "OpenSky 持续限流")


def _number(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out and abs(out) < 1e15 else None  # NaN / inf guard


def parse_states(data: dict, received: str) -> list[dict]:
    rows: list[dict] = []
    for s in (data or {}).get("states") or []:
        if not isinstance(s, (list, tuple)) or len(s) < 12:
            continue
        lon, lat = _number(s[5]), _number(s[6])
        if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
            continue
        if s[8] is True:  # on ground
            continue
        contact = s[4] or s[3]
        observed = received
        if contact is not None:
            try:
                observed = to_iso(datetime.fromtimestamp(float(contact), tz=timezone.utc))
            except (ValueError, TypeError, OSError):
                pass
        rows.append({
            "station_id": str(s[0]), "source_id": SOURCE_ID,
            "observed_at": observed, "received_at": received,
            "lon": lon, "lat": lat,
            "values": {
                "callsign": (s[1] or "").strip() if isinstance(s[1], str) else "",
                "country": s[2],
                "baro_altitude_m": _number(s[7]),
                "true_track_deg": _number(s[10]),
                "vertical_rate_ms": _number(s[11]),
                "velocity_ms": _number(s[9]),
            },
            "raw_ref": "",
        })
    if len(rows) > 6000:
        # Keep the feed order: sorting by altitude discarded all low-level
        # traffic, which looked unrealistic once aircraft fly near the surface.
        rows = rows[:6000]
    return rows


def refresh(fetcher: Callable[[str], dict] | None = None) -> dict:
    try:
        received = to_iso(datetime.now(timezone.utc))
        rows = parse_states(fetch_states(fetcher), received)
        if not rows:
            raise IngestError("NO_EVENTS", "OpenSky 未返回航班")
        repo.insert_observations(rows)
        from .base import mark_success as _success
        _success(SOURCE_ID, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
