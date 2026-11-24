"""Global natural-hazard feeds: GDACS, EONET and NASA FIRMS.

All three feeds are point events. GDACS additionally publishes tropical-cyclone
track points as ``realtime/gdacs_tracks.json``. EONET rows that duplicate a
recent GDACS/FIRMS event are suppressed so the globe does not stack markers for
the same physical event.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import get_settings
from ..fields.timeutil import normalize_lat, normalize_lon, parse_iso, to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

GDACS_URL = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/SEARCH"
EONET_URL = "https://eonet.gsfc.nasa.gov/api/v3/events/geojson?status=open&days=14"
FIRMS_URL = ("https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}"
             "/VIIRS_SNPP_NRT/world/1")

EVENT_TYPES = {"EQ", "TC", "FL", "VO", "DR", "WF"}
EONET_CATEGORY_TYPE = {
    "earthquakes": "EQ", "severeStorms": "TC", "tropicalCyclones": "TC",
    "floods": "FL", "volcanoes": "VO", "drought": "DR", "wildfires": "WF",
}
MAX_TRACK_STORMS = 6
MAX_FIRMS_EVENTS = 6000
DEDUP_KM = 250.0
DEDUP_HOURS = 72.0


def _get_json(url: str, timeout: float = 40) -> Any:
    result = fetch(url, timeout=timeout)
    try:
        return json.loads(result.payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise IngestError("BAD_JSON", f"上游响应不是 JSON：{e}") from e


def _get_text(url: str, timeout: float = 40) -> str:
    result = fetch(url, timeout=timeout)
    try:
        return result.payload.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise IngestError("BAD_TEXT", f"上游响应不是 UTF-8 文本：{e}") from e


def _iso(value: Any, fallback: str) -> str:
    """Normalise GDACS/EONET timestamps to ISO-8601 UTC."""
    if not value:
        return fallback
    if isinstance(value, (int, float)):
        return to_iso(datetime.fromtimestamp(value / 1000, tz=timezone.utc))
    s = str(value).strip()
    try:
        return to_iso(parse_iso(s))
    except ValueError:
        pass
    for fmt in ("%d %b %Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return to_iso(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc))
        except ValueError:
            continue
    return fallback


def _float(value: Any) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _write_realtime(name: str, payload: dict) -> None:
    root = get_settings().data_root / "realtime"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


# --------------------------------------------------------------------------- GDACS
def gdacs_rows(data: dict, received: str) -> list[dict]:
    rows: list[dict] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        etype = str(props.get("eventtype") or "")
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if etype not in EVENT_TYPES or len(coords) < 2:
            continue
        lon, lat = _float(coords[0]), _float(coords[1])
        if lon is None or lat is None:
            continue
        event_id = str(props.get("eventid") or props.get("glide") or "unknown")
        episode = str(props.get("episodeid") or "0")
        severity = props.get("severitydata") or {}
        values = {
            "event_type": etype,
            "event_id": event_id,
            "episode_id": episode,
            "name": props.get("name") or props.get("eventname") or etype,
            "alert_level": props.get("alertlevel"),
            "alert_score": _float(props.get("alertscore")),
            "country": props.get("country"),
            "source": props.get("source"),
            "severity_text": severity.get("severitytext"),
            "from_date": props.get("fromdate"),
            "to_date": props.get("todate"),
            "is_current": str(props.get("iscurrent")).lower() == "true",
            "report_url": (props.get("url") or {}).get("report"),
            "geometry_url": (props.get("url") or {}).get("geometry"),
        }
        rows.append({
            "station_id": f"gdacs-{event_id}-{episode}",
            "source_id": "gdacs",
            # Ongoing alerts (e.g. droughts) carry an old modification time but
            # a recent end date. Prefer the event's own validity end so active
            # alerts survive the cleanup window; fall back to modification time.
            "observed_at": _iso(props.get("todate") or props.get("datemodified"), received),
            "received_at": received,
            "lon": normalize_lon(lon), "lat": normalize_lat(lat),
            "values": values, "raw_ref": "",
        })
    return rows


def _gdacs_track(feature: dict, received: str) -> dict | None:
    props = feature.get("properties") or {}
    event_id = str(props.get("eventid") or "")
    data = _get_json(f"https://www.gdacs.org/gdacsapi/api/events/geteventdata"
                     f"?eventtype=TC&eventid={event_id}", timeout=25)
    pdata = (data.get("properties") if isinstance(data, dict) else {}) or {}
    timeline_url = None
    for impact in pdata.get("impacts") or []:
        resource = impact.get("resource") or {}
        if resource.get("timeline"):
            timeline_url = resource["timeline"]
            break
    if not timeline_url:
        return None
    timeline = _get_json(timeline_url, timeout=25)
    items = (((timeline.get("channel") or {}).get("item")) or [])
    points = timeline_points(items, received)
    if not points:
        return None
    return {
        "id": event_id,
        "name": pdata.get("name") or props.get("name"),
        "source": pdata.get("source") or props.get("source"),
        "points": points,
    }


def timeline_points(items: Any, received: str) -> list[dict]:
    """Convert GDACS timeline items into sorted lon/lat/time track points."""
    if isinstance(items, dict):
        items = [items]
    points = []
    for item in items:
        lon, lat = _float(item.get("longitude")), _float(item.get("latitude"))
        if lon is None or lat is None:
            continue
        status = item.get("storm_status")
        points.append({
            "lon": normalize_lon(lon), "lat": normalize_lat(lat),
            "time": _iso(item.get("advisory_datetime"), received),
            "wind_kmh": _float(item.get("wind_speed")),
            "status": status[0] if isinstance(status, list) and status else status,
            "forecast": str(item.get("actual")).lower() != "true",
        })
    points.sort(key=lambda x: x["time"])
    return points


def refresh_gdacs() -> dict:
    src = "gdacs"
    try:
        received = to_iso(datetime.now(timezone.utc))
        data = _get_json(GDACS_URL)
        rows = gdacs_rows(data, received)
        if not rows:
            raise IngestError("NO_EVENTS", "GDACS 未返回灾害事件")
        repo.insert_observations(rows)
        repo.delete_observations_before([src], to_iso(
            datetime.now(timezone.utc) - timedelta(days=14)))

        tracks = []
        current = [f for f in data.get("features") or []
                   if (f.get("properties") or {}).get("eventtype") == "TC"
                   and str((f.get("properties") or {}).get("iscurrent")).lower() == "true"]
        for feature in current[:MAX_TRACK_STORMS]:
            try:
                track = _gdacs_track(feature, received)
                if track:
                    tracks.append(track)
            except Exception as e:  # noqa: BLE001 - one bad storm must not fail the feed
                log.warning("GDACS 轨迹获取失败：%s", e)
        _write_realtime("gdacs_tracks.json", {"tracks": tracks, "received_at": received})
        mark_success(src, {"events": len(rows), "tracks": len(tracks)})
        return {"ok": True, "events": len(rows), "tracks": len(tracks)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


# --------------------------------------------------------------------------- EONET
def _centroid(geometry: dict) -> tuple[float, float] | None:
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Point" and len(coords) >= 2:
        lon, lat = _float(coords[0]), _float(coords[1])
        return (lon, lat) if lon is not None and lat is not None else None
    if geometry.get("type") in ("Polygon", "MultiLineString", "LineString"):
        ring = coords[0] if coords and isinstance(coords[0], list) else coords
        pts = [(_float(p[0]), _float(p[1])) for p in ring
               if isinstance(p, list) and len(p) >= 2]
        pts = [(x, y) for x, y in pts if x is not None and y is not None]
        if pts:
            return sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts)
    return None


def eonet_rows(data: dict, received: str,
               primary: list[dict] | None = None) -> list[dict]:
    primary = primary or []
    rows: list[dict] = []
    for feature in data.get("features") or []:
        props = feature.get("properties") or {}
        point = _centroid(feature.get("geometry") or {})
        if not point:
            continue
        lon, lat = normalize_lon(point[0]), normalize_lat(point[1])
        categories = props.get("categories") or []
        category = categories[0].get("id") if categories else None
        etype = EONET_CATEGORY_TYPE.get(category, "")
        event_id = str(props.get("id") or "")
        observed = _iso(props.get("date"), received)
        if primary and etype:
            try:
                observed_dt = parse_iso(observed)
                duplicate = any(
                    p["lon"] is not None and p["lat"] is not None
                    and (p.get("values") or {}).get("event_type") == etype
                    and _haversine_km(lon, lat, p["lon"], p["lat"]) <= DEDUP_KM
                    and abs((parse_iso(p["observed_at"]) - observed_dt).total_seconds())
                    <= DEDUP_HOURS * 3600
                    for p in primary
                )
                if duplicate:
                    continue
            except (ValueError, TypeError, KeyError):
                pass
        magnitude = _float(props.get("magnitudeValue"))
        sources = props.get("sources") or []
        rows.append({
            "station_id": f"eonet-{event_id}",
            "source_id": "eonet",
            "observed_at": observed, "received_at": received,
            "lon": lon, "lat": lat,
            "values": {
                "event_type": etype, "category": category, "event_id": event_id,
                "title": props.get("title"), "description": props.get("description"),
                "magnitude": magnitude, "magnitude_unit": props.get("magnitudeUnit"),
                "source": sources[0].get("id") if sources else "EONET",
                "link": props.get("link"),
            },
            "raw_ref": "",
        })
    return rows


def refresh_eonet() -> dict:
    src = "eonet"
    try:
        received = to_iso(datetime.now(timezone.utc))
        data = _get_json(EONET_URL)
        primary = repo.query_stations(None, received, max_age_minutes=14 * 24 * 60,
                                      source_id="gdacs")
        primary += repo.query_stations(None, received, max_age_minutes=2 * 24 * 60,
                                       source_id="nasa_firms")
        rows = eonet_rows(data, received, primary)
        repo.insert_observations(rows)
        repo.delete_observations_before([src], to_iso(
            datetime.now(timezone.utc) - timedelta(days=14)))
        mark_success(src, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


# --------------------------------------------------------------------------- FIRMS
def firms_rows(text: str, received: str) -> list[dict]:
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for raw in reader:
        lon, lat = _float(raw.get("longitude")), _float(raw.get("latitude"))
        if lon is None or lat is None:
            continue
        date = str(raw.get("acq_date") or "").strip()
        hhmm = str(raw.get("acq_time") or "").strip().zfill(4)
        if not date or len(hhmm) < 4:
            continue
        observed = _iso(f"{date}T{hhmm[:2]}:{hhmm[2:4]}:00", received)
        frp = _float(raw.get("frp"))
        bright = _float(raw.get("bright_ti4"))
        confidence = str(raw.get("confidence") or "").strip()
        satellite = str(raw.get("satellite") or "VIIRS").strip()
        rows.append({
            "station_id": f"firms-{satellite}-{date}-{hhmm}-{lon:.3f}-{lat:.3f}",
            "source_id": "nasa_firms",
            "observed_at": observed, "received_at": received,
            "lon": normalize_lon(lon), "lat": normalize_lat(lat),
            "values": {
                "event_type": "WF", "satellite": satellite,
                "brightness_k": bright, "frp_mw": frp,
                "confidence": confidence, "day_night": raw.get("daynight"),
                "acq_date": date, "acq_time": hhmm,
            },
            "raw_ref": "",
        })
    # Keep the strongest detections when the global feed exceeds the render budget.
    rank = {"h": 3, "n": 2, "l": 1}
    rows.sort(key=lambda r: (r["values"]["frp_mw"] or -1,
                             r["values"]["brightness_k"] or -1,
                             rank.get(r["values"]["confidence"].lower(), 0)), reverse=True)
    return rows[:MAX_FIRMS_EVENTS]


def refresh_firms() -> dict:
    src = "nasa_firms"
    try:
        key = get_settings().firms_map_key.strip()
        if not key:
            raise IngestError("MISSING_API_KEY", "未配置 EARTHSIM_FIRMS_MAP_KEY，FIRMS 火点未启用")
        received = to_iso(datetime.now(timezone.utc))
        text = _get_text(FIRMS_URL.format(key=key), timeout=90)
        rows = firms_rows(text, received)
        if not rows:
            raise IngestError("NO_EVENTS", "FIRMS 未返回火点")
        repo.insert_observations(rows)
        repo.delete_observations_before([src], to_iso(
            datetime.now(timezone.utc) - timedelta(hours=36)))
        mark_success(src, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


_REFRESHERS = {
    "gdacs": refresh_gdacs,
    "eonet": refresh_eonet,
    "nasa_firms": refresh_firms,
}


def refresh(source: str | None = None) -> dict:
    if source:
        fn = _REFRESHERS.get(source)
        if not fn:
            raise IngestError("UNKNOWN_SOURCE", f"未知灾害源 {source}")
        return fn()
    return {name: fn() for name, fn in _REFRESHERS.items()}
