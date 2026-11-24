"""Volumetric cloud density from multi-level GFS relative humidity.

Downloads 6 isobaric RH levels (1000/925/850/700/600/500 hPa) in one GRIB
Filter request, converts RH to a cloud-density proxy, and publishes a compact
3D float32 volume (xyz layout) as an independent dataset for raymarching.

IMPORTANT: this is a *visualisation proxy* derived from humidity, NOT true
cloud water content. The UI must label it accordingly.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import get_settings
from ..fields import grid as gmod
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success
from . import gfs

log = logging.getLogger(__name__)
SOURCE_ID = "gfs_volume"
DATASET_ID = "gfs-volume"
LAYER_ID = "cloud_volume"
FILTER_URL = gfs.FILTER_URL
# Surface -> upper atmosphere. z index 0 = 1000 hPa (near surface).
LEVELS = [1000, 925, 850, 700, 600, 500]
DECIMATE = 4  # 1441x721 -> 360x181 (keeps volume ~1.5 MB)
RH_THRESHOLD = 70.0   # RH below this -> no cloud
RH_FULL = 100.0       # RH at/above this -> full density

# Horizontal grid after decimation (lon -180..180, lat -90..90, south->north).
# decode uses values[::4] on 1440 samples -> 360 columns (indices 0..1436).
VOL_NX = 1440 // DECIMATE  # 360
VOL_NY = (721 - 1) // DECIMATE + 1   # 181
HGRID = gmod.GridSpec("EPSG:4326", VOL_NX, VOL_NY, -180.0, -90.0,
                      0.25 * DECIMATE, 0.25 * DECIMATE, wrap_longitude=True)


def filter_params(init: datetime, lead: int) -> dict[str, str]:
    p: dict[str, str] = {
        "dir": f"/gfs.{init:%Y%m%d}/{init:%H}/atmos",
        "file": f"gfs.t{init:%H}z.pgrb2.0p25.f{lead:03d}",
        "var_RH": "on",
    }
    for lv in LEVELS:
        p[f"lev_{lv}_mb"] = "on"
    return p


def _staged_path(init: datetime, lead: int) -> Path:
    root = get_settings().data_root
    return root / "raw/gfs-volume" / f"{init:%Y%m%dT%H%M}Z" / f"f{lead:03d}" / "rh.grib2"


def download(init: datetime, lead: int) -> Path:
    s = get_settings()
    r = fetch(FILTER_URL, params=filter_params(init, lead),
              validator=lambda resp: gfs.validate_grib(resp.content), timeout=120)
    if len(r.payload) > s.max_download_bytes:
        raise IngestError("SOURCE_TOO_LARGE", "体积云 RH 文件超过字节上限")
    path = _staged_path(init, lead)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.payload)
    tmp.replace(path)
    return path


def decode_volume(path: Path, *, decoder: Callable[[Path], np.ndarray] | None = None) -> np.ndarray:
    """Return cloud density volume shaped (ny, nx, nz) in project lat/lon order."""
    if decoder is not None:
        return decoder(path)
    try:
        import eccodes  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise IngestError("MISSING_ECODES", "未安装 ecCodes", {"hint": "pip install eccodes"}) from e

    levels: dict[int, np.ndarray] = {}
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                if eccodes.codes_get(gid, "shortName") != "r":
                    continue
                lv = int(eccodes.codes_get(gid, "level"))
                if lv not in LEVELS:
                    continue
                vals = np.asarray(eccodes.codes_get_values(gid), dtype=np.float32).reshape(721, 1440)
                # GRIB native north-to-south / 0..360 -> project south-to-north / -180..180.
                vals = np.flipud(vals)
                vals = np.roll(vals, 720, axis=1)
                levels[lv] = vals[::DECIMATE, ::DECIMATE]
            finally:
                eccodes.codes_release(gid)
    if len(levels) < 3:
        raise IngestError("INSUFFICIENT_LEVELS", "可用湿度层不足，无法构造体积云", {"levels": list(levels)})
    # Stack in LEVELS order (surface -> upper). Missing levels fall back to nearest available.
    stack = []
    for lv in LEVELS:
        stack.append(levels.get(lv, levels[min(levels, key=lambda k: abs(k - lv))]))
    rh = np.stack(stack, axis=-1).astype(np.float32)  # (ny, nx, nz)
    density = np.clip((rh - RH_THRESHOLD) / (RH_FULL - RH_THRESHOLD), 0.0, 1.0)
    return density


def _volume_bytes(density: np.ndarray) -> bytes:
    """Serialize to xyz layout: index = x + y*nx + z*nx*ny (Data3DTexture order)."""
    # density is (ny, nx, nz); move z to front -> (nz, ny, nx) C-order matches xyz.
    vol = np.moveaxis(density, 2, 0).astype("<f4")
    return vol.tobytes(order="C")


def build_frame(init: datetime, lead: int, density: np.ndarray) -> dict:
    snap_id = f"gfs-volume-{init:%Y%m%dT%H%M}Z"
    valid = to_iso(init + timedelta(hours=lead))
    fid = f"{snap_id}-f{lead:03d}"
    rel = f"derived/{snap_id}/{fid}.bin"
    root = get_settings().data_root
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = _volume_bytes(density)
    p.write_bytes(payload)
    dig = hashlib.sha256(payload).hexdigest()
    ny, nx, nz = density.shape
    grid = HGRID.to_dict()
    manifest = {
        "schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
        "kind": "forecast", "source_id": SOURCE_ID, "layer_id": LAYER_ID,
        "init_time": to_iso(init), "valid_time": valid,
        "layer_type": "volume", "grid": grid,
        "volume": {"nx": int(nx), "ny": int(ny), "nz": int(nz),
                   "levels_hpa": LEVELS, "layout": "xyz", "dtype": "float32",
                   "quantity": "cloud_density_proxy_from_RH",
                   "note": "基于多层相对湿度的云密度代理，非真实云水含量"},
        "encoding": {"dtype": "float32", "layout": "xyz"},
    }
    return {
        "frame_id": fid, "layer_id": LAYER_ID, "level_type": "volume", "level_value": 0,
        "valid_time": valid, "bbox": {"west": -180, "south": -90, "east": 180, "north": 90},
        "grid": grid, "fields": [{"id": "cloud_density", "unit": "1"}],
        "manifest": manifest,
        "assets": [{"asset_id": fid + "-vol", "role": "volume", "relative_path": rel,
                    "media_type": "application/octet-stream", "sha256": dig, "bytes": len(payload)}],
    }


def refresh(max_leads: int | None = None) -> dict:
    ini = gfs.probe_latest()
    if ini is None:
        err = IngestError("NO_CYCLE", "未找到可用 GFS 起报批次")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    max_leads = max_leads if max_leads is not None else get_settings().volume_lead_max_hours
    frames = []
    for lead in range(0, max_leads + 1):
        try:
            path = _staged_path(ini, lead)
            if not path.exists():
                path = download(ini, lead)
            density = decode_volume(path)
            frames.append(build_frame(ini, lead, density))
        except (IngestError, OSError) as e:
            # A failed lead must not discard earlier ones; publish the
            # contiguous prefix already collected (degraded timeline).
            log.warning("体积云 lead f%03d 失败：%s", lead, e)
            break
    if not frames:
        err = IngestError("NO_FRAMES", "体积云未生成任何帧")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}

    degraded = len(frames) < max_leads + 1
    snap_id = f"gfs-volume-{ini:%Y%m%dT%H%M}Z"
    snapshot = {
        "snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": to_iso(ini),
        "init_time": to_iso(ini), "payload_version": "1", "state": "published",
        "published_at": to_iso(datetime.now(timezone.utc)),
        "details": {"source": "NOAA GFS multi-level RH (cloud density proxy)",
                    "levels_hpa": LEVELS, "note": "可视化代理，非真实云水含量",
                    "partial": degraded, "leads": list(range(len(frames)))},
    }
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast", "体积云（多层湿度代理）",
                        "NOAA NCEP", "https://www.nco.ncep.noaa.gov/pmb/products/gfs/")
    repo.insert_snapshot(snapshot, frames, publish=True)
    mark_success(SOURCE_ID, {"init_time": to_iso(ini), "frames": len(frames)})
    return {"ok": True, "snapshot_id": snap_id, "frames": len(frames),
            "leads": list(range(len(frames))), "partial": degraded,
            "shape": [VOL_NY, VOL_NX, len(LEVELS)]}
