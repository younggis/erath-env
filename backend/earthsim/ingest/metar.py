"""NOAA AWC METAR adapter (guide section 3.4).

GET /api/data/metar with ids + format=json. Raw reports are preserved. Units
are normalized to the project contract (m/s, degrees, null for missing). VRB,
calm and censored visibility (>10km) keep their qualifiers instead of being
silently coerced.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

SOURCE_ID = "awc_metar"
DATASET_ID = "awc-metar"
API_URL = "https://aviationweather.gov/api/data/metar"
# A broad set of major international airports across every continent so the
# global station layer is dense and useful, not a handful of dots.
DEFAULT_STATIONS = [
    # East Asia
    "RJTT", "RJCC", "RJAA", "RKSI", "RKSI", "ZSPD", "ZBAA", "ZGGG", "ZUCK",
    "VHHH", "WSSS", "WMKK", "VTBS", "VVNB", "RKSI",
    # South Asia / Middle East
    "VIDP", "VABB", "OMDB", "OMAA", "OTHH", "OERK", "LTBA", "LTFM",
    # Europe
    "EGLL", "EGCC", "EHAM", "LFPG", "EDDF", "LEMD", "LIRF", "LSZH",
    "UUEE", "ULAA", "EPLL", "ESSA", "EIDW", "LKPR", "EHAM",
    # Africa
    "HECA", "HEMM", "FACT", "FAOR", "DNMM", "GMMN", "FZAA", "HAAA",
    # Americas
    "KJFK", "KLAX", "KORD", "KATL", "KDFW", "KMIA", "KSEA", "KSFO",
    "CYYZ", "CYVR", "MMMX", "SBGR", "SCEL", "SAEZ", "SKBO",
    # Oceania
    "YSSY", "YMML", "NZAA", "NZWN",
]
# de-duplicate while preserving order
DEFAULT_STATIONS = list(dict.fromkeys(DEFAULT_STATIONS))


def _knots_to_ms(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v) * 0.514444, 3)
    except (TypeError, ValueError):
        return None


def _visibility(raw) -> dict:
    """Return {meters, raw, qualifier, lower_bound} preserving censoring."""
    if raw is None or raw == "":
        return {"meters": None, "raw": None, "qualifier": None, "lower_bound": None}
    s = str(raw).strip()
    if s.upper() in {"CAVOK", "9999"}:
        return {"meters": 10000.0, "raw": s, "qualifier": ">=", "lower_bound": 10000.0}
    if s.startswith(">"):
        try:
            m = float(s[1:]) * 1609.344
            return {"meters": m, "raw": s, "qualifier": ">", "lower_bound": m}
        except ValueError:
            pass
    if s.endswith("+"):  # AWC uses e.g. "6+" for greater-than-six miles
        try:
            m = float(s[:-1]) * 1609.344
            return {"meters": m, "raw": s, "qualifier": ">", "lower_bound": m}
        except ValueError:
            pass
    if s.startswith("M"):
        try:
            m = float(s[1:]) * 1609.344
            return {"meters": m, "raw": s, "qualifier": "<", "lower_bound": None}
        except ValueError:
            pass
    try:
        miles = float(s)
        m = miles * 1609.344
        return {"meters": m, "raw": s, "qualifier": "=", "lower_bound": m}
    except ValueError:
        return {"meters": None, "raw": s, "qualifier": None, "lower_bound": None}


def _wind_dir(raw) -> dict:
    if raw is None or raw == "":
        return {"degrees": None, "variable": False, "calm": False, "raw": None}
    if str(raw).upper() == "VRB":
        return {"degrees": None, "variable": True, "calm": False, "raw": str(raw)}
    if raw == 0 or str(raw).zfill(3) == "000":
        return {"degrees": 0.0, "variable": False, "calm": True, "raw": str(raw)}
    try:
        return {"degrees": float(raw), "variable": False, "calm": False, "raw": str(raw)}
    except (TypeError, ValueError):
        return {"degrees": None, "variable": False, "calm": False, "raw": str(raw)}


def normalize(report: dict, received_at: str) -> dict:
    """Normalize one AWC JSON report into the observation contract."""
    def num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    obs_at = report.get("reportTime") or report.get("obsTime")
    if isinstance(obs_at, (int, float)):
        obs_at = datetime.fromtimestamp(float(obs_at), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "station_id": str(report.get("icaoId") or report.get("stationId") or ""),
        "source_id": SOURCE_ID,
        "observed_at": to_iso(datetime.fromisoformat(str(obs_at).replace("Z", "+00:00"))) if obs_at else received_at,
        "revision": str(report.get("reportTime") or "1"),
        "received_at": received_at,
        "lon": num(report.get("lon")),
        "lat": num(report.get("lat")),
        "values": {
            "temp_c": num(report.get("temp")),
            "dewpoint_c": num(report.get("dewp")),
            "wind_speed_ms": _knots_to_ms(report.get("wspd")),
            "wind_gust_ms": _knots_to_ms(report.get("wgst")),
            "wind_direction": _wind_dir(report.get("wdir")),
            "visibility": _visibility(report.get("visib")),
            "weather_phenomena": report.get("wxString"),
            "flight_category": report.get("fltCat"),
            "raw_report": report.get("rawOb"),
            "station_elevation_m": num(report.get("elev")),
        },
        "raw_ref": f"raw/metar/{received_at[:10]}.json",
    }


def refresh(stations: list[str] | None = None) -> dict:
    stations = stations or DEFAULT_STATIONS
    received = to_iso(datetime.now(timezone.utc))
    try:
        r = fetch(API_URL, params={"ids": ",".join(stations), "format": "json"})
    except IngestError as e:
        mark_failure(SOURCE_ID, e)
        return {"ok": False, "error": e.code, "message": str(e)}
    if not r.payload.strip():  # AWC 204 No Content -> keep cache, record freshness
        mark_failure(SOURCE_ID, IngestError("NO_REPORT", "上游 204：无报告"))
        return {"ok": False, "error": "NO_REPORT", "kept_cache": True}
    try:
        data = json.loads(r.payload)
    except json.JSONDecodeError as e:
        err = IngestError("BAD_JSON", "METAR 响应不是 JSON")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    if isinstance(data, dict):
        data = data.get("reports") or data.get("data") or []
    rows = [normalize(d, received) for d in data if d.get("icaoId") or d.get("stationId")]
    # A missing AWC coordinate must never become a phantom station at 0,0.
    rows = [r for r in rows
            if r["lon"] is not None and r["lat"] is not None
            and -180 <= r["lon"] <= 180 and -90 <= r["lat"] <= 90]
    root = get_settings().data_root
    rel = f"raw/metar/{received[:19].replace(':','')}.json"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(r.payload)
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "observation", "NOAA AWC METAR 机场观测",
                        "NOAA Aviation Weather Center", "https://aviationweather.gov/data/api/")
    repo.insert_observations(rows)
    # Publish a snapshot so freshness can be assessed from the newest report.
    times = sorted(r["observed_at"] for r in rows if r.get("observed_at"))
    snap_id = f"awc-metar-{received[:19].replace(':','').replace('-','').replace('T','T')}"
    snapshot = {
        "snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": received[:19],
        "observed_start": times[0] if times else received,
        "observed_end": times[-1] if times else received,
        "payload_version": "1", "state": "published", "published_at": received,
        "details": {"stations": len(rows), "source_url": r.url,
                    "station_ids": [r["station_id"] for r in rows]},
    }
    repo.insert_snapshot(snapshot, [], publish=True)
    mark_success(SOURCE_ID, {"stations": len(rows), "source_url": r.url})
    return {"ok": True, "observations": len(rows), "received_at": received, "snapshot_id": snap_id}
