"""NOAA OISST v2.1 daily global sea-surface temperature adapter.

The yearly PSL NetCDF is ~420 MB, so this adapter uses NOAA NCEI ERDDAP to
request only the latest daily field, subsampled 2x2 to a 0.5° grid (~1 MB).
ERDDAP brackets must be percent-encoded; the dataset's AVHRR-only analysis
has a real publication lag of roughly two weeks, which is recorded in the
source status rather than hidden.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import numpy as np

from ..config import get_settings
from ..fields import grid as gmod
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "noaa_oisst"
DATASET_ID = "noaa-oisst"
ERDDAP_BASE = ("https://www.ncei.noaa.gov/erddap/griddap/"
               "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.nc")
# last time, surface depth, every 2nd latitude/longitude -> 360x720
QUERY = "sst[(last)][0][0:2:719][0:2:1439]"
OISST_GRID = gmod.GridSpec("EPSG:4326", nx=721, ny=360, lon0=-179.875, lat0=-89.875,
                           dx=0.5, dy=0.5, wrap_longitude=True)
BBOX = {"west": -180, "south": -89.875, "east": 180, "north": 89.625}


def request_url() -> str:
    return f"{ERDDAP_BASE}?{quote(QUERY, safe='')}"


def validate_nc(payload: bytes) -> None:
    if payload[:4] not in (b"CDF\x01", b"CDF\x02"):
        raise IngestError("BAD_NETCDF", "下载内容不是 NetCDF-3", {"len": len(payload)})


def _staged_path() -> Path:
    return get_settings().data_root / "raw/oisst/latest.nc"


def download() -> Path:
    result = fetch(request_url(), timeout=90, validator=lambda r: validate_nc(r.content))
    path = _staged_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(result.payload)
    tmp.replace(path)
    return path


def decode_nc(path: Path, *, reader: Callable[[Path], tuple[dict, np.ndarray]] | None = None) -> tuple[str, np.ndarray]:
    """Return ``(observed_time_iso, values[ny,nx])`` on the project grid.

    ``reader`` is injectable for unit tests; it returns variable dictionaries
    and the SST array as stored by ERDDAP (time, depth, latitude, longitude).
    """
    if reader is None:
        def reader(p: Path):  # noqa: A001 - keeps the signature simple
            from scipy.io import netcdf_file
            with netcdf_file(str(p), "r", mmap=False) as nc:
                raw = np.array(nc.variables["sst"][:], dtype=np.float32)
                t = float(np.asarray(nc.variables["time"][:]).ravel()[0])
                variables = {k: np.array(v[:]) for k, v in nc.variables.items()}
            return variables, raw
    variables, raw = reader(path)
    arr = np.squeeze(raw)
    if arr.ndim != 2 or arr.shape != (360, 720):
        raise IngestError("BAD_GRID", f"OISST 网格尺寸异常：{arr.shape}")
    # ERDDAP longitudes are 0.125..359.625; roll to -180..180 then add seam.
    arr = np.roll(arr, 360, axis=1)
    rect = np.empty((OISST_GRID.ny, OISST_GRID.nx), dtype=np.float32)
    rect[:, :720] = arr
    rect[:, 720] = arr[:, 0]
    rect[rect < -500] = np.nan  # OISST land/missing sentinel is -999.
    t = float(np.asarray(variables["time"]).ravel()[0])
    observed = to_iso(datetime.fromtimestamp(t, tz=timezone.utc))
    return observed, rect.astype(np.float32)


def build_frames(observed: str, values: np.ndarray) -> list[dict]:
    snap_id = f"noaa-oisst-{observed[:10].replace('-', '')}"
    fid = f"{snap_id}-sst"
    rel = f"derived/{snap_id}/{fid}.bin"
    path = get_settings().data_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    gmod.write_grid_binary(path, values[:, :, None])
    dig = hashlib.sha256(path.read_bytes()).hexdigest()
    meta = {"level": {"type": "surface", "value": 0, "unit": ""},
            "fields": [{"id": "sst", "unit": "degC"}]}
    return [{
        "frame_id": fid, "layer_id": "sst", "level_type": "surface", "level_value": 0.0,
        "valid_time": observed, "bbox": BBOX,
        "grid": OISST_GRID.to_dict(), "fields": meta["fields"],
        "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                     "kind": "forecast", "source_id": SOURCE_ID, "layer_id": "sst",
                     "init_time": observed, "valid_time": observed, "level": meta["level"],
                     "grid": gmod.describe_grid(OISST_GRID), "fields": meta["fields"],
                     "encoding": {"dtype": "float32", "missing": "nan"}},
        "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": rel,
                    "media_type": "application/octet-stream", "sha256": dig,
                    "bytes": path.stat().st_size}],
    }]


def refresh() -> dict:
    try:
        path = _staged_path()
        if not path.exists():
            path = download()
        else:
            validate_nc(path.read_bytes()[:4])
        observed, values = decode_nc(path)
        frames = build_frames(observed, values)
        snap_id = f"noaa-oisst-{observed[:10].replace('-', '')}"
        repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast",
                            "NOAA OISST v2.1 全球日海温（AVHRR，约两周滞后）",
                            "NOAA NCEI", "https://www.ncei.noaa.gov/products/optimum-interpolation-sst")
        active = repo.get_active_snapshot(DATASET_ID)
        publish = not (active and active.get("init_time") and observed < active["init_time"])
        snapshot = {"snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": observed,
                    "init_time": observed, "payload_version": "1", "state": "published",
                    "published_at": to_iso(datetime.now(timezone.utc)),
                    "details": {"source_url": request_url(), "resolution": "0.5° (ERDDAP 2x2 降采样)",
                                "publication_lag": "上游 AVHRR-only 分析约滞后两周"}}
        repo.insert_snapshot(snapshot, frames, publish=publish)
        mark_success(SOURCE_ID, {"observed": observed, "frames": len(frames), "publish": publish})
        return {"ok": True, "snapshot_id": snap_id, "observed": observed,
                "frames": len(frames), "publish": publish}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
