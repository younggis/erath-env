"""GDACS disaster alerts with official impact polygons.

The SEARCH feed is point-based; each feature carries a ``url.geometry`` link
to a GeoJSON FeatureCollection that may contain Polygon / MultiPolygon impact
areas and LineString tracks. This adapter parses those polygons, keeps a
bounded set of the highest-alert events, and stores the point events in the
shared observations table (the same realtime event source used by the globe).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, mark_failure, mark_success
from . import disasters

log = logging.getLogger(__name__)

SOURCE_ID = "gdacs"
MAX_POLYGON_EVENTS = 24
EVENT_CLASSES = {
    "EQ": "地震", "TS": "海啸", "FL": "洪水", "VO": "火山",
    "TC": "热带气旋", "DR": "干旱", "WF": "野火", "LS": "滑坡",
}
ALERT_COLORS = {"Red": "#ff4d5e", "Orange": "#ffa23a", "Green": "#5fe08a"}


def classify_event(event_type: str | None) -> str:
    code = str(event_type or "").upper()
    return EVENT_CLASSES.get(code, code or "未知灾害")


def _coord(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if -180 <= out <= 180 or -90 <= out <= 90 else None


def parse_ring(coords: Any) -> list[list[float]] | None:
    """Validate and flatten one linear ring into [[lon, lat], ...]."""
    if not isinstance(coords, (list, tuple)):
        return None
    ring: list[list[float]] = []
    for pair in coords:
        if not isinstance(pair, (list, tuple)) or len(pair) < 2:
            continue
        lon, lat = _coord(pair[0]), _coord(pair[1])
        if lon is None or lat is None:
            continue
        ring.append([round(lon, 4), round(lat, 4)])
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(list(ring[0]))
    return ring


def parse_geojson(data: Any, received: str) -> list[dict]:
    """Extract impact polygons from a GDACS geometry FeatureCollection."""
    polygons: list[dict] = []
    if not isinstance(data, dict):
        return polygons
    for feature in data.get("features") or []:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") or {}
        gtype = str(geometry.get("type") or "")
        props = feature.get("properties") or {}
        coords = geometry.get("coordinates")
        rings: list[list[list[float]]] = []
        if gtype == "Polygon" and isinstance(coords, list):
            ring = parse_ring(coords[0] if coords else None)
            if ring:
                rings.append(ring)
        elif gtype == "MultiPolygon" and isinstance(coords, list):
            for poly in coords:
                if isinstance(poly, list) and poly:
                    ring = parse_ring(poly[0])
                    if ring:
                        rings.append(ring)
        if not rings:
            continue
        polygons.append({
            "event_id": str(props.get("eventid") or ""),
            "event_type": str(props.get("eventtype") or ""),
            "event_class": classify_event(props.get("eventtype")),
            "name": props.get("name") or props.get("eventname") or "",
            "alert_level": props.get("alertlevel"),
            "alert_color": ALERT_COLORS.get(str(props.get("alertlevel")), "#8aa0b5"),
            "description": props.get("htmldescription") or props.get("description") or "",
            "report_url": (props.get("url") or {}).get("report") or "",
            "rings": rings,
            "received_at": received,
        })
    return polygons


def _rank(feature: dict) -> int:
    props = feature.get("properties") or {}
    level = {"Red": 3, "Orange": 2, "Green": 1}.get(str(props.get("alertlevel")), 0)
    return level


def refresh(fetcher: Callable[[str], Any] | None = None,
            max_polygon_events: int | None = None) -> dict:
    fetcher = fetcher or disasters._get_json
    try:
        received = to_iso(datetime.now(timezone.utc))
        data = fetcher(disasters.GDACS_URL)
        features = data.get("features") or [] if isinstance(data, dict) else []
        rows = disasters.gdacs_rows(data, received)
        if not rows:
            raise IngestError("NO_EVENTS", "GDACS 未返回灾害事件")

        limit = max_polygon_events or MAX_POLYGON_EVENTS
        candidates = sorted(features, key=_rank, reverse=True)[:limit]
        polygons: list[dict] = []
        for feature in candidates:
            props = feature.get("properties") or {}
            url = (props.get("url") or {}).get("geometry")
            if not url:
                continue
            try:
                geometry = fetcher(url)
                polygons.extend(parse_geojson(geometry, received))
            except Exception as e:  # noqa: BLE001
                log.warning("GDACS geometry fetch failed for %s: %s", props.get("eventid"), e)

        repo.insert_observations(rows)
        repo.delete_observations_before([SOURCE_ID], to_iso(
            datetime.now(timezone.utc) - timedelta(days=14)))

        # Preserve the existing tropical-cyclone track feed.
        tracks = []
        current = [f for f in features
                   if (f.get("properties") or {}).get("eventtype") == "TC"
                   and str((f.get("properties") or {}).get("iscurrent")).lower() == "true"]
        for feature in current[:disasters.MAX_TRACK_STORMS]:
            try:
                track = disasters._gdacs_track(feature, received)
                if track:
                    tracks.append(track)
            except Exception as e:  # noqa: BLE001
                log.warning("GDACS track failed: %s", e)
        disasters._write_realtime("gdacs_tracks.json", {"tracks": tracks, "received_at": received})

        root = get_settings().data_root
        path = root / "realtime/gdacs_polygons.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"polygons": polygons, "received_at": received,
                              "events": len(rows)}, ensure_ascii=False)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

        mark_success(SOURCE_ID, {"events": len(rows), "polygons": len(polygons)})
        return {"ok": True, "events": len(rows), "polygons": len(polygons)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}


def read_polygons() -> dict:
    path = get_settings().data_root / "realtime/gdacs_polygons.json"
    if not path.exists():
        return {"polygons": [], "received_at": None, "events": 0}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"polygons": [], "received_at": None, "events": 0}
