"""Background ingest task manager: non-blocking refresh with in-flight dedup."""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Callable

from .config import get_settings
from .catalog import repository as repo
from .freshness import assess
from .ingest import cams, disasters, gefs, gfs, metar, fixtures, hrrr, ifs, ndbc, oisst, openaq, realtime, volume, wave
from .fields.timeutil import to_iso

TASKS: dict[str, dict] = {}
_LOCK = threading.Lock()
_FUNCTIONS: dict[str, Callable] = {
    "noaa_gfs": gfs.refresh,
    "awc_metar": metar.refresh,
    "hrrr": hrrr.refresh,
    "ecmwf_ifs": ifs.refresh,
    "gfs_volume": volume.refresh,
    "noaa_wave": wave.refresh,
    "noaa_oisst": oisst.refresh,
    "cams": cams.refresh,
    "noaa_gefs": gefs.refresh,
    "noaa_ndbc": ndbc.refresh,
    "openaq": openaq.refresh,
    "usgs_quake": realtime.refresh_quakes,
    "opensky": realtime.refresh_flights,
    "nhc_storm": realtime.refresh_storms,
    "nasa_cme": realtime.refresh_cme,
    "noaa_aurora": realtime.refresh_aurora,
    "noaa_solar_wind": realtime.refresh_solar_wind,
    "gdacs": disasters.refresh_gdacs,
    "eonet": disasters.refresh_eonet,
    "nasa_firms": disasters.refresh_firms,
    "realtime_all": realtime.refresh,
    "demo": fixtures.install_all,
}
_ACTIVE: set[str] = set()


def request_refresh(source_id: str) -> dict:
    """Start (or reuse) a background refresh. Returns 202-style task info."""
    if source_id not in _FUNCTIONS:
        raise KeyError(source_id)
    with _LOCK:
        if source_id in _ACTIVE:
            # reuse the in-flight task id
            existing = next((tid for tid, t in TASKS.items()
                             if t["source"] == source_id and t["state"] == "running"), None)
            if existing:
                return {"task_id": existing, "source": source_id, "reused": True, "state": "running"}
        task_id = uuid.uuid4().hex[:12]
        TASKS[task_id] = {"source": source_id, "state": "queued", "started": None,
                          "finished": None, "result": None, "error": None}
        _ACTIVE.add(source_id)
    t = threading.Thread(target=_run, args=(task_id, source_id), daemon=True, name=f"ingest-{source_id}")
    t.start()
    return {"task_id": task_id, "source": source_id, "reused": False, "state": "queued",
            "status_url": f"/api/v1/sources/refresh/{task_id}"}


def _run(task_id: str, source_id: str) -> None:
    with _LOCK:
        TASKS[task_id].update({"state": "running", "started": to_iso(datetime.now(timezone.utc))})
    try:
        result = _FUNCTIONS[source_id]()
        with _LOCK:
            TASKS[task_id].update({"state": "succeeded", "result": result,
                                   "finished": to_iso(datetime.now(timezone.utc))})
    except Exception as e:  # noqa: BLE001
        with _LOCK:
            TASKS[task_id].update({"state": "failed", "error": str(e),
                                   "finished": to_iso(datetime.now(timezone.utc))})
    finally:
        with _LOCK:
            _ACTIVE.discard(source_id)


def get_task(task_id: str) -> dict | None:
    with _LOCK:
        t = TASKS.get(task_id)
        return dict(t) if t else None


def auto_refresh_if_needed() -> None:
    """Called at API startup: in live mode, kick off refresh for any stale source."""
    if get_settings().data_mode == "fixture":
        request_refresh("demo")
        return
    status = assess()
    for ds in status["datasets"]:
        if ds["source_kind"] != "live":
            continue
        if ds["state"] in ("missing", "stale", "unknown", "candidate"):
            try:
                request_refresh(ds["source_id"])
            except KeyError:
                pass
