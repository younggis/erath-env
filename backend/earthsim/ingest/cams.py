"""CAMS global atmospheric composition via Open-Meteo's keyless gridded API.

The underlying model is CAMS Global Atmospheric Composition Forecasts (0.4°,
twice daily, CC BY 4.0). Requesting the raw ADS GRIB requires an account, so
this adapter samples the same CAMS fields through Open-Meteo at 5° resolution
and publishes three honest, downsampled global layers. Zero values fade to
transparent in the renderer so clean air does not paint the whole globe.
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..config import get_settings
from ..fields import grid as gmod
from ..fields.timeutil import parse_iso, to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "cams"
DATASET_ID = "cams-air-quality"
API_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
VARIABLES = ("aerosol_optical_depth", "dust", "pm2_5")
LAYER_FOR_VAR = {"aerosol_optical_depth": "cams_aod", "dust": "cams_dust", "pm2_5": "cams_pm25"}
UNITS = {"aerosol_optical_depth": "1", "dust": "ug/m3", "pm2_5": "ug/m3"}
BATCH = 500
BATCH_DELAY_SECONDS = 1.5
CAMS_GRID = gmod.GridSpec("EPSG:4326", nx=73, ny=36, lon0=-180.0, lat0=-87.5,
                          dx=5.0, dy=5.0, wrap_longitude=True)
BBOX = {"west": -180, "south": -87.5, "east": 180, "north": 87.5}


def sample_coordinates() -> list[tuple[float, float]]:
    """Row-major (lat, lon) samples: 36 latitudes x 72 longitudes.

    The 73rd seam column is duplicated from column 0 after fetch, so the
    published grid keeps the project's -180..180 wrap contract.
    """
    return [(lat, lon)
            for lat in np.arange(-87.5, 90.0, 5.0)
            for lon in np.arange(-180.0, 180.0, 5.0)]


def _get_json(params: dict[str, Any]) -> Any:
    result = fetch(API_URL, params=params, timeout=60)
    try:
        return json.loads(result.payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise IngestError("BAD_JSON", f"Open-Meteo 响应不是 JSON：{e}") from e


def fetch_grid() -> tuple[str, dict[str, np.ndarray]]:
    coords = sample_coordinates()
    values: dict[str, np.ndarray] = {v: np.full((CAMS_GRID.ny, CAMS_GRID.nx), np.nan, dtype=np.float32)
                                     for v in VARIABLES}
    received = to_iso(datetime.now(timezone.utc))
    for batch_index, start in enumerate(range(0, len(coords), BATCH)):
        if batch_index:
            time.sleep(BATCH_DELAY_SECONDS)
        chunk = coords[start:start + BATCH]
        rows = _get_json({
            "latitude": ",".join(f"{lat:.1f}" for lat, _ in chunk),
            "longitude": ",".join(f"{lon:.1f}" for _, lon in chunk),
            "current": ",".join(VARIABLES),
            "domains": "cams_global",
            "timeformat": "unixtime",
        })
        if not isinstance(rows, list) or len(rows) != len(chunk):
            raise IngestError("BAD_BATCH", f"CAMS 批量响应数量不符：{len(rows) if isinstance(rows, list) else 'n/a'}")
        for offset, item in enumerate(rows):
            idx = start + offset
            j, i = divmod(idx, CAMS_GRID.nx - 1)
            current = item.get("current") or {}
            ts = current.get("time")
            if ts:
                received = to_iso(datetime.fromtimestamp(float(ts), tz=timezone.utc))
            for var in VARIABLES:
                raw = current.get(var)
                if raw is not None:
                    values[var][j, i] = np.float32(raw)
    for var in VARIABLES:
        values[var][:, CAMS_GRID.nx - 1] = values[var][:, 0]  # wrap seam
        values[var][values[var] < -900] = np.nan
    return received, values


def build_frames(observed: str, values: dict[str, np.ndarray]) -> list[dict]:
    snap_id = f"cams-air-quality-{observed[:10].replace('-', '')}"
    frames: list[dict] = []
    for var in VARIABLES:
        layer = LAYER_FOR_VAR[var]
        fid = f"{snap_id}-{layer}"
        rel = f"derived/{snap_id}/{fid}.bin"
        path = get_settings().data_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        arr = values[var][:, :, None]
        gmod.write_grid_binary(path, arr)
        dig = hashlib.sha256(path.read_bytes()).hexdigest()
        level = {"type": "surface", "value": 0, "unit": ""}
        fields = [{"id": layer, "unit": UNITS[var]}]
        frames.append({
            "frame_id": fid, "layer_id": layer, "level_type": "surface", "level_value": 0.0,
            "valid_time": observed, "bbox": BBOX,
            "grid": CAMS_GRID.to_dict(), "fields": fields,
            "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                         "kind": "forecast", "source_id": SOURCE_ID, "layer_id": layer,
                         "init_time": observed, "valid_time": observed, "level": level,
                         "grid": gmod.describe_grid(CAMS_GRID), "fields": fields,
                         "encoding": {"dtype": "float32", "missing": "nan"}},
            "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": rel,
                        "media_type": "application/octet-stream", "sha256": dig,
                        "bytes": path.stat().st_size}],
        })
    return frames


def _read_cached():
    path = _staged_path()
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        observed = payload["observed"]
        values = {v: np.asarray(payload[v], dtype=np.float32) for v in VARIABLES}
        return observed, values
    except (OSError, ValueError, KeyError):
        return None


def _save_grid(observed: str, values: dict[str, np.ndarray]) -> None:
    path = _staged_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"observed": observed,
               **{v: values[v].tolist() for v in VARIABLES}}
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def refresh() -> dict:
    try:
        cached = _read_cached()
        limit = get_settings().cams_stale_after_hours * 3600
        if cached and (datetime.now(timezone.utc) - parse_iso(cached[0])).total_seconds() <= limit:
            observed, values = cached
        else:
            observed, values = fetch_grid()
            _save_grid(observed, values)
        frames = build_frames(observed, values)
        snap_id = f"cams-air-quality-{observed[:10].replace('-', '')}"
        repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast",
                            "CAMS 全球大气成分（AOD/沙尘/PM2.5，Open-Meteo 5° 降采样）",
                            "CAMS / Open-Meteo",
                            "https://atmosphere.copernicus.eu/")
        active = repo.get_active_snapshot(DATASET_ID)
        publish = not (active and active.get("init_time") and observed < active["init_time"])
        snapshot = {"snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": observed,
                    "init_time": observed, "payload_version": "1", "state": "published",
                    "published_at": to_iso(datetime.now(timezone.utc)),
                    "details": {"source_url": API_URL, "resolution": "5° sample of CAMS 0.4° global",
                                "license": "CC BY 4.0", "variables": list(VARIABLES)}}
        repo.insert_snapshot(snapshot, frames, publish=publish)
        mark_success(SOURCE_ID, {"observed": observed, "frames": len(frames), "publish": publish})
        return {"ok": True, "snapshot_id": snap_id, "observed": observed,
                "frames": len(frames), "publish": publish}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}


def _staged_path() -> Path:  # kept for symmetry with other adapters; not used
    return get_settings().data_root / "raw/cams/latest.json"
