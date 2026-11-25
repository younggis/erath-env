"""NASA FIRMS active-fire hotspots (MODIS / VIIRS near real time).

Parses the FIRMS CSV feed through the shared disaster parser, then applies a
configurable FRP (fire radiative power) threshold so only meaningful thermal
anomalies reach the globe. Without a MAP_KEY the adapter reports a disabled
status instead of failing the ingest pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, mark_failure, mark_success
from .disasters import FIRMS_URL, _get_text, firms_rows

log = logging.getLogger(__name__)

SOURCE_ID = "nasa_firms"
DEFAULT_MIN_FRP_MW = 10.0


def frp_of(row: dict) -> float:
    value = (row.get("values") or {}).get("frp_mw")
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def parse_fires(text: str, received: str, min_frp: float | None = None) -> list[dict]:
    """Parse FIRMS CSV and keep rows with FRP >= threshold.

    Every returned row is a valid EPSG:4326 observation (lon -180..180,
    lat -90..90) because the shared parser normalises coordinates.
    """
    threshold = DEFAULT_MIN_FRP_MW if min_frp is None else max(0.0, float(min_frp))
    rows = firms_rows(text, received)
    return [r for r in rows if frp_of(r) >= threshold]


def status() -> dict:
    key = (get_settings().firms_map_key or "").strip()
    return {
        "enabled": bool(key),
        "configured": bool(key),
        "note": ("NASA FIRMS 全球实时火点" if key
                 else "未配置 EARTHSIM_FIRMS_MAP_KEY，FIRMS 火点未启用"),
        "source_url": FIRMS_URL,
    }


def refresh() -> dict:
    settings = get_settings()
    key = (settings.firms_map_key or "").strip()
    if not key:
        # Graceful degradation: no socket / HTTP call, no failure marker.
        return {"ok": False, "enabled": False, "error": "MISSING_API_KEY",
                "note": status()["note"]}
    try:
        received = to_iso(datetime.now(timezone.utc))
        text = _get_text(FIRMS_URL.format(key=key), timeout=90)
        rows = parse_fires(text, received, settings.firms_min_frp_mw)
        if not rows:
            raise IngestError("NO_EVENTS", "FIRMS 无满足 FRP 阈值的火点")
        repo.insert_observations(rows)
        repo.delete_observations_before([SOURCE_ID], to_iso(
            datetime.now(timezone.utc) - timedelta(hours=36)))
        mark_success(SOURCE_ID, {"events": len(rows), "min_frp_mw": settings.firms_min_frp_mw})
        return {"ok": True, "events": len(rows), "min_frp_mw": settings.firms_min_frp_mw}
    except Exception as e:  # noqa: BLE001
        # httpx exceptions embed the full request URL; never persist the MAP_KEY.
        message = str(e).replace(key, "***") if key else str(e)
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", message)
        if isinstance(e, IngestError):
            err.message = message
            err.details = {k: (v.replace(key, "***") if isinstance(v, str) and key else v)
                           for k, v in err.details.items()}
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
