"""Real-time event & space-weather adapters.

Point events (earthquakes, aircraft, storms, CMEs) are stored in the existing
``observations`` table and served via ``/api/v1/realtime/events``. Gridded aurora
probability and solar-wind time series are written to ``data_root/realtime`` and
served as compact JSON. Every feed is fetched independently so one failure never
blocks the others.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from . import disasters
from .base import IngestError, mark_failure, mark_success

log = logging.getLogger(__name__)

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
OPENSKY_URL = "https://opensky-network.org/api/states/all"
NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"
DONKI_URL = ("https://api.nasa.gov/DONKI/CME?startDate={start}&endDate={end}&api_key=DEMO_KEY")
AURORA_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
WIND_URL = "https://services.swpc.noaa.gov/json/rtsw/rtsw_wind_1m.json"
BZ_URL = "https://services.swpc.noaa.gov/products/summary/solar-wind-mag-field.json"
KP_URL = "https://services.swpc.noaa.gov/products/noaa-planetary-k-index.json"

EVENT_SOURCES = {
    "usgs_quake": "USGS 实时地震",
    "opensky": "OpenSky 实时航班",
    "nhc_storm": "NOAA NHC 热带气旋",
    "nasa_cme": "NASA DONKI 日冕物质抛射",
    "gdacs": "GDACS 全球灾害预警",
    "eonet": "NASA EONET 自然事件",
    "nasa_firms": "NASA FIRMS 全球火点",
}
FIELD_SOURCES = {
    "noaa_aurora": "NOAA SWPC 极光概率",
    "noaa_solar_wind": "NOAA SWPC 太阳风 / 磁场",
}
ALL_SOURCES = {**EVENT_SOURCES, **FIELD_SOURCES}

# Freshness tolerance per source (minutes). Fast streams update every 1-3 min;
# event-driven / slow feeds (storms, CMEs) can legitimately be hours old while
# still being the latest available. Used by freshness.assess().
SOURCE_STALE_MINUTES: dict[str, int] = {
    "usgs_quake": 15,
    "opensky": 15,
    "noaa_aurora": 30,
    "noaa_solar_wind": 30,
    "nhc_storm": 360,     # NHC issues advisories ~6h
    "nasa_cme": 720,      # CME events are sporadic (hours apart)
    "gdacs": 360,         # event-driven; multi-hazard alerts
    "eonet": 1440,        # curated natural events, often daily
    "nasa_firms": 360,    # satellite overpasses, not continuous
}


def _get_json(url: str, *, timeout: float = 40) -> Any:
    import httpx
    with httpx.Client(timeout=timeout, follow_redirects=True,
                      headers={"User-Agent": "earthsim/1.0 (local research simulator)"}) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _now_iso() -> str:
    return to_iso(datetime.now(timezone.utc))


def _cleanup(source_ids: list[str], hours: int = 6) -> None:
    before = to_iso(datetime.now(timezone.utc) - timedelta(hours=hours))
    try:
        repo.delete_observations_before(source_ids, before)
    except Exception as e:  # noqa: BLE001
        log.warning("realtime cleanup failed: %s", e)


# --------------------------------------------------------------------------- earthquakes
def refresh_quakes() -> dict:
    src = "usgs_quake"
    try:
        data = _get_json(USGS_URL)
        received = _now_iso()
        rows = []
        for feat in data.get("features", []):
            p = feat.get("properties") or {}
            geom = (feat.get("geometry") or {}).get("coordinates") or []
            if len(geom) < 2 or geom[0] is None or geom[1] is None:
                continue
            ms = p.get("time")
            observed = to_iso(datetime.fromtimestamp(ms / 1000, tz=timezone.utc)) if ms else received
            rows.append({
                "station_id": str(feat.get("id") or p.get("title") or ms),
                "source_id": src, "observed_at": observed, "received_at": received,
                "lon": float(geom[0]), "lat": float(geom[1]),
                "values": {
                    "mag": p.get("mag"), "place": p.get("place"), "depth_km": geom[2] if len(geom) > 2 else None,
                    "title": p.get("title"), "url": p.get("url"), "tsunami": p.get("tsunami"),
                    "sig": p.get("sig"), "status": p.get("status"),
                },
                "raw_ref": "",
            })
        if not rows:
            raise IngestError("NO_EVENTS", "USGS 未返回地震事件")
        repo.insert_observations(rows)
        _cleanup([src])
        mark_success(src, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


# --------------------------------------------------------------------------- flights
def refresh_flights() -> dict:
    src = "opensky"
    try:
        data = _get_json(OPENSKY_URL, timeout=90)
        received = _now_iso()
        rows = []
        for s in data.get("states") or []:
            if len(s) < 8 or s[5] is None or s[6] is None or s[8]:
                continue  # skip missing position / on-ground
            contact = s[4] or s[3] or data.get("time")
            observed = to_iso(datetime.fromtimestamp(float(contact), tz=timezone.utc)) if contact else received
            rows.append({
                "station_id": str(s[0]), "source_id": src, "observed_at": observed, "received_at": received,
                "lon": float(s[5]), "lat": float(s[6]),
                "values": {
                    "callsign": (s[1] or "").strip(), "country": s[2],
                    "altitude_m": s[7], "velocity_ms": s[9], "track_deg": s[10], "vertical_rate_ms": s[11],
                },
                "raw_ref": "",
            })
        # Cap the store for the render budget (prefer highest altitude / airborne).
        if len(rows) > 6000:
            rows.sort(key=lambda r: (r["values"].get("altitude_m") or 0), reverse=True)
            rows = rows[:6000]
        if not rows:
            raise IngestError("NO_EVENTS", "OpenSky 未返回航班")
        repo.insert_observations(rows)
        _cleanup([src], hours=2)
        mark_success(src, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


# --------------------------------------------------------------------------- tropical storms
def refresh_storms() -> dict:
    src = "nhc_storm"
    try:
        data = _get_json(NHC_URL)
        received = _now_iso()
        rows = []
        for st in data.get("activeStorms") or []:
            lat, lon = st.get("latitude"), st.get("longitude")
            if lat is None or lon is None:
                continue
            def first(*keys, default=None):
                for k in keys:
                    if st.get(k) is not None:
                        return st[k]
                return default
            observed = str(first("lastUpdate", "last_updated", "timestamp", default=received))
            rows.append({
                "station_id": str(first("id", "stormId", "name", default=st.get("binNumber"))),
                "source_id": src, "observed_at": observed, "received_at": received,
                "lon": float(lon), "lat": float(lat),
                "values": {
                    "name": first("name", default="Unnamed"),
                    "classification": first("classification", "stormType"),
                    "intensity": first("intensity", "intensityValue"),
                    "max_wind_kt": first("maxWind", "maxWindSpeed"),
                    "min_pressure_mb": first("minPressure", "pressure"),
                    "move_dir": first("movementDir", "movementDirection"),
                    "move_speed_kt": first("movementSpeed"),
                    "forecasts": first("forecasts", default=[]),
                },
                "raw_ref": "",
            })
        # Empty active-storm list is a valid state (no storms) — record success.
        repo.insert_observations(rows)
        _cleanup([src], hours=24)
        mark_success(src, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


# --------------------------------------------------------------------------- CME
def refresh_cme() -> dict:
    src = "nasa_cme"
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=5)
        data = _get_json(DONKI_URL.format(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d")))
        received = _now_iso()
        rows = []
        for ev in data:
            analyses = ev.get("cmeAnalyses") or []
            best = next((a for a in analyses if a.get("isMostAccurate")), analyses[0] if analyses else {})
            start_time = ev.get("startTime")
            observed = (start_time.replace("Z", "+00:00") + ":00" if start_time and len(start_time) == 16
                        else (start_time or received))
            rows.append({
                "station_id": str(ev.get("activityID") or start_time),
                "source_id": src, "observed_at": observed, "received_at": received,
                "lon": 0.0, "lat": float(best.get("latitude") or 0.0),
                "values": {
                    "activity_id": ev.get("activityID"), "note": (ev.get("note") or "")[:400],
                    "speed_kms": best.get("speed"), "half_angle_deg": best.get("halfAngle"),
                    "type": best.get("type"), "link": ev.get("link"),
                },
                "raw_ref": "",
            })
        if not rows:
            raise IngestError("NO_EVENTS", "DONKI 未返回 CME 事件")
        repo.insert_observations(rows)
        _cleanup([src], hours=24 * 7)
        mark_success(src, {"events": len(rows)})
        return {"ok": True, "events": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


# --------------------------------------------------------------------------- aurora oval
def refresh_aurora() -> dict:
    src = "noaa_aurora"
    try:
        data = _get_json(AURORA_URL)
        coords = data.get("coordinates") or []
        if not coords:
            raise IngestError("NO_DATA", "OVATION 未返回极光数据")
        # Grid is 1° lon × 1° lat (360×181); flatten for compact transport.
        nx, ny = 360, 181
        flat = [0] * (nx * ny)
        for lon, lat, val in coords:
            ix = int((float(lon) + 180) % 360)
            iy = int(float(lat) + 90)
            if 0 <= ix < nx and 0 <= iy < ny:
                flat[iy * nx + ix] = int(val)
        kp = _latest_kp()
        payload = {
            "observation_time": data.get("Observation Time"),
            "forecast_time": data.get("Forecast Time"),
            "nx": nx, "ny": ny, "lat0": -90, "lat1": 90, "lon0": -180, "lon1": 180,
            "data": flat, "kp": kp, "received_at": _now_iso(),
        }
        _write_realtime("aurora.json", payload)
        mark_success(src, {"points": len(flat), "kp": kp})
        return {"ok": True, "points": len(flat), "kp": kp}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


def _latest_kp() -> float | None:
    try:
        rows = _get_json(KP_URL, timeout=20)
        if isinstance(rows, list):
            for row in reversed(rows):
                if row.get("Kp") not in (None, ""):
                    return float(row["Kp"])
    except Exception:  # noqa: BLE001
        pass
    return None


# --------------------------------------------------------------------------- solar wind
def refresh_solar_wind() -> dict:
    src = "noaa_solar_wind"
    try:
        wind = _get_json(WIND_URL)
        bz_rows = _get_json(BZ_URL, timeout=20)
        bz = None
        if isinstance(bz_rows, list) and bz_rows:
            bz = bz_rows[-1].get("bz_gsm")
        rows = []
        for w in wind:
            if w.get("proton_speed") is None:
                continue
            rows.append({
                "time": w.get("time_tag"), "speed": w.get("proton_speed"),
                "density": w.get("proton_density"), "temperature": w.get("proton_temperature"),
            })
        if not rows:
            raise IngestError("NO_DATA", "SWPC 未返回太阳风数据")
        latest = rows[0]
        payload = {
            "received_at": _now_iso(), "time": latest["time"],
            "speed_kms": latest["speed"], "density_pcc": latest["density"],
            "temperature_k": latest["temperature"], "bz_gsm": bz,
            "kp": _latest_kp(),
            "history": rows[:180][::-1],  # oldest -> newest, 3 hours
        }
        _write_realtime("solar_wind.json", payload)
        mark_success(src, {"samples": len(rows), "speed": latest["speed"], "bz": bz})
        return {"ok": True, "samples": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(src, err)
        return {"ok": False, "error": err.code}


def _write_realtime(name: str, payload: dict) -> None:
    root = get_settings().data_root / "realtime"
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(p)


def read_realtime(name: str) -> dict | None:
    p = get_settings().data_root / "realtime" / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- aggregation
_REFRESHERS = {
    "usgs_quake": refresh_quakes,
    "opensky": refresh_flights,
    "nhc_storm": refresh_storms,
    "nasa_cme": refresh_cme,
    "noaa_aurora": refresh_aurora,
    "noaa_solar_wind": refresh_solar_wind,
    **disasters._REFRESHERS,
}


def refresh(source: str | None = None) -> dict:
    """Refresh one source, or all with per-source error isolation."""
    if source:
        fn = _REFRESHERS.get(source)
        if not fn:
            raise IngestError("UNKNOWN_SOURCE", f"未知实时源 {source}")
        return fn()
    results = {}
    for name, fn in _REFRESHERS.items():
        try:
            results[name] = fn()
        except Exception as e:  # noqa: BLE001
            results[name] = {"ok": False, "error": str(e)[:120]}
    return {"ok": True, "sources": results}
