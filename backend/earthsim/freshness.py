"""Data freshness / liveness assessment.

Classifies each dataset as live / stale / missing based on the active
snapshot's timestamps and the configured freshness thresholds. This is the
single source of truth for the UI's "real-time vs simulated" indicator.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .config import get_settings
from .catalog import repository as repo
from .fields.timeutil import parse_iso, to_iso

# dataset_id -> (source_id, kind, timestamp field, threshold, unit)
DATASETS = {
    "noaa-gfs": ("noaa_gfs", "forecast", "init_time", "gfs_stale_after_hours", "hours"),
    "awc-metar": ("awc_metar", "observation", "observed_end", "metar_stale_after_minutes", "minutes"),
    "noaa-hrrr": ("noaa_hrrr", "forecast", "published_at", "gfs_stale_after_hours", "hours"),
    "ecmwf-ifs": ("ecmwf_ifs", "forecast", "init_time", "gfs_stale_after_hours", "hours"),
    "gfs-volume": ("gfs_volume", "forecast", "init_time", "gfs_stale_after_hours", "hours"),
    "noaa-wave": ("noaa_wave", "forecast", "init_time", "gfs_stale_after_hours", "hours"),
    "noaa-oisst": ("noaa_oisst", "forecast", "init_time", "oisst_stale_after_hours", "hours"),
    "cams-air-quality": ("cams", "forecast", "init_time", "cams_stale_after_hours", "hours"),
    "noaa-gefs": ("noaa_gefs", "forecast", "init_time", "gfs_stale_after_hours", "hours"),
    "noaa-ndbc": ("noaa_ndbc", "observation", "observed_end", "ndbc_stale_after_minutes", "minutes"),
    "openaq-air-quality": ("openaq", "observation", "observed_end", "openaq_stale_after_hours", "hours"),
}


def _threshold_minutes(settings, field: str, unit: str) -> float:
    value = getattr(settings, field)
    return value * (60 if unit == "hours" else 1)


def assess() -> dict:
    s = get_settings()
    now = datetime.now(timezone.utc)
    results: list[dict] = []
    for dataset_id, (source_id, kind, field, thr_field, unit) in DATASETS.items():
        snap = repo.get_active_snapshot(dataset_id)
        src = next((x for x in repo.get_sources() if x["source_id"] == source_id), {})
        entry: dict[str, Any] = {
            "dataset_id": dataset_id, "source_id": source_id, "kind": kind,
        }
        if not snap:
            entry.update({"state": "missing", "fresh": False, "age_minutes": None,
                          "timestamp": None, "last_error": src.get("last_error_code")})
            results.append(entry); continue
        ts_raw = snap.get(field)
        try:
            ts = parse_iso(ts_raw) if ts_raw else None
        except Exception:
            ts = None
        age_min = (now - ts).total_seconds() / 60 if ts else None
        thr = _threshold_minutes(s, thr_field, unit)
        if snap.get("state") != "published":
            state = "candidate"
        elif age_min is None:
            state = "unknown"
        elif age_min < 0:
            state = "future"
        elif age_min <= thr:
            state = "live"
        else:
            state = "stale"
        entry.update({
            "state": state, "fresh": state == "live",
            "snapshot_id": snap["snapshot_id"], "timestamp": ts_raw,
            "age_minutes": None if age_min is None else round(age_min, 1),
            "threshold_minutes": thr,
            "last_success": src.get("last_success_at"), "last_error": src.get("last_error_code"),
        })
        results.append(entry)

    # Real-time event/space-weather feeds have no grid snapshot; assess them
    # from the source registry's last_success_at.
    from .ingest.realtime import ALL_SOURCES, SOURCE_STALE_MINUTES
    sources = {x["source_id"]: x for x in repo.get_sources()}
    thr = s.realtime_poll_seconds / 60
    for source_id, label in ALL_SOURCES.items():
        src = sources.get(source_id, {})
        ts_raw = src.get("last_success_at")
        ts = None
        if ts_raw:
            try:
                ts = parse_iso(ts_raw)
            except Exception:
                ts = None
        age = (now - ts).total_seconds() / 60 if ts else None
        # Per-source tolerance: fast streams need fresh data, but storm/CME
        # feeds are event-driven and can be hours old while still current.
        limit = SOURCE_STALE_MINUTES.get(source_id, thr * 3)
        if age is None:
            state = "missing"
        elif age <= limit:
            state = "live"
        else:
            state = "stale"
        results.append({
            "dataset_id": f"realtime-{source_id}", "source_id": source_id, "kind": "observation",
            "label": label,
            "state": state, "fresh": state == "live", "timestamp": ts_raw,
            "age_minutes": None if age is None else round(age, 1),
            "threshold_minutes": round(limit, 1),
            "last_success": ts_raw, "last_error": src.get("last_error_code"),
        })
    return {
        "server_time": to_iso(now),
        "datasets": results,
        "all_live": all(r["fresh"] for r in results),
        "note": "在线模式：数据来自真实上游，按 freshness 阈值判定",
    }
