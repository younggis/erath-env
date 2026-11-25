"""NOAA GEFS 0.5° ensemble mean/spread adapter.

NOMADS publishes precomputed ensemble mean (``geavg``) and spread (``gespr``)
files, so the client never downloads all 31 members. This adapter publishes
mean, spread and a clearly-labelled Gaussian-approximation probability field
for 10 m wind exceeding 10 m/s.
"""
from __future__ import annotations

import hashlib
import logging
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from ..config import get_settings
from ..fields import grid as gmod
from ..fields.timeutil import gfs_cycles, to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "noaa_gefs"
DATASET_ID = "noaa-gefs"
FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gefs_atmos_0p50a.pl"

GEFS_GRID = gmod.GridSpec("EPSG:4326", nx=721, ny=361, lon0=-180.0, lat0=-90.0,
                          dx=0.5, dy=0.5, wrap_longitude=True)
BBOX = {"west": -180, "south": -90, "east": 180, "north": 90}
FIELDS = ("10u", "10v", "2t")
LAYER_META = {
    "gefs_wind10_mean": {"fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}]},
    "gefs_wind10_spread": {"fields": [{"id": "spread", "unit": "m/s"}]},
    "gefs_temp2m_mean": {"fields": [{"id": "temp", "unit": "K"}]},
    "gefs_temp2m_spread": {"fields": [{"id": "spread", "unit": "K"}]},
    "gefs_wind_prob": {"fields": [{"id": "probability", "unit": "%"}]},
}


def filter_params(init: datetime, lead: int, kind: str) -> dict[str, str]:
    return {
        "dir": f"/gefs.{init:%Y%m%d}/{init:%H}/atmos/pgrb2ap5",
        "file": f"{kind}.t{init:%H}z.pgrb2a.0p50.f{lead:03d}",
        "lev_10_m_above_ground": "on", "var_UGRD": "on", "var_VGRD": "on",
        "lev_2_m_above_ground": "on", "var_TMP": "on",
    }


def validate_grib(payload: bytes) -> None:
    if payload[:4] != b"GRIB":
        raise IngestError("BAD_GRIB", "下载内容不是有效 GRIB 消息", {"len": len(payload)})


def probe_latest(now: datetime | None = None, attempts: int = 6) -> datetime | None:
    import httpx
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for init in gfs_cycles(now, attempts):
            try:
                r = client.get(FILTER_URL, params=filter_params(init, 0, "geavg"))
                if r.status_code == 200 and r.content[:4] == b"GRIB":
                    return init
            except httpx.HTTPError:
                continue
    return None


def _staged_path(init: datetime, lead: int, kind: str) -> Path:
    return (get_settings().data_root / "raw/gefs" / f"{init:%Y%m%dT%H%M}Z"
            / f"f{lead:03d}" / f"{kind}.grib2")


def download(init: datetime, lead: int, kind: str) -> Path:
    result = fetch(FILTER_URL, params=filter_params(init, lead, kind),
                   timeout=60, validator=lambda r: validate_grib(r.content))
    path = _staged_path(init, lead, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(result.payload)
    tmp.replace(path)
    return path


def normalize_grid(native: np.ndarray) -> np.ndarray:
    """Convert GEFS native 90N->90S / 0..360E to south->north / -180..180 with seam."""
    arr = np.roll(np.flipud(native), 360, axis=1)
    rect = np.empty((GEFS_GRID.ny, GEFS_GRID.nx), dtype=np.float32)
    rect[:, :720] = arr
    rect[:, 720] = arr[:, 0]
    return rect.astype(np.float32)


def decode_messages(path: Path, decoder: Callable[[Path], dict] | None = None) -> dict:
    """Return ``{shortName: ndarray(ny,nx)}`` on the project grid."""
    if decoder is not None:
        raw = decoder(path)
        return {k: normalize_grid(v) for k, v in raw.items()}
    try:
        import eccodes  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise IngestError("MISSING_ECODES", "未安装 ecCodes，无法解码 GRIB", {"hint": "pip install eccodes"}) from e

    out: dict[str, np.ndarray] = {}
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short = str(eccodes.codes_get(gid, "shortName"))
                if short not in FIELDS:
                    continue
                native = eccodes.codes_get_values(gid).reshape(361, 720)
                out[short] = normalize_grid(native)
            finally:
                eccodes.codes_release(gid)
    return out


def _erf_probability(speed: np.ndarray, sigma: np.ndarray, threshold: float = 10.0) -> np.ndarray:
    """P(wind > threshold) via a Gaussian CDF; documented as an approximation."""
    scale = np.maximum(np.nan_to_num(sigma, nan=1.0), 0.25) * math.sqrt(2.0)
    z = np.nan_to_num((speed - threshold) / scale, nan=-10.0, posinf=10.0, neginf=-10.0)
    erf = np.vectorize(math.erf)(np.clip(z, -6, 6))
    return np.clip((0.5 * (1.0 + erf)) * 100.0, 0, 100).astype(np.float32)


def build_frames(init: datetime, mean: dict, spread: dict, leads: list[int],
                 by_valid: dict[tuple[str, str], dict] | None = None) -> list[dict]:
    snap_id = f"noaa-gefs-{init:%Y%m%dT%H%M}Z"
    frames: list[dict] = []
    for lead in leads:
        valid = to_iso(init + timedelta(hours=lead))
        if by_valid is not None:
            mean_at = by_valid.get(("geavg", valid)) or {}
            spread_at = by_valid.get(("gespr", valid)) or {}
            u, v = mean_at.get("10u"), mean_at.get("10v")
            su, sv = spread_at.get("10u"), spread_at.get("10v")
            temp, stemp = mean_at.get("2t"), spread_at.get("2t")
        else:
            u, v = mean.get("10u"), mean.get("10v")
            su, sv = spread.get("10u"), spread.get("10v")
            temp, stemp = mean.get("2t"), spread.get("2t")
        if u is None or v is None or su is None or sv is None or temp is None or stemp is None:
            raise IngestError("INCOMPLETE_BATCH", f"缺少 GEFS 核心字段 @{valid}")
        speed = np.hypot(u, v)
        sigma = np.hypot(su, sv)
        arrays = {
            "gefs_wind10_mean": np.stack([u, v], axis=-1),
            "gefs_wind10_spread": sigma[:, :, None],
            "gefs_temp2m_mean": temp[:, :, None],
            "gefs_temp2m_spread": stemp[:, :, None],
            "gefs_wind_prob": _erf_probability(speed, sigma)[:, :, None],
        }
        for layer, arr in arrays.items():
            fid = f"{snap_id}-{layer}-f{lead:03d}"
            rel = f"derived/{snap_id}/{fid}.bin"
            path = get_settings().data_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            gmod.write_grid_binary(path, arr)
            dig = hashlib.sha256(path.read_bytes()).hexdigest()
            level = {"type": "height_agl", "value": 10 if "wind" in layer else 2, "unit": "m"}
            fields = LAYER_META[layer]["fields"]
            frames.append({
                "frame_id": fid, "layer_id": layer,
                "level_type": level["type"], "level_value": float(level["value"]),
                "valid_time": valid, "bbox": BBOX,
                "grid": GEFS_GRID.to_dict(), "fields": fields,
                "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                             "kind": "forecast", "source_id": SOURCE_ID, "layer_id": layer,
                             "init_time": to_iso(init), "valid_time": valid, "level": level,
                             "grid": gmod.describe_grid(GEFS_GRID), "fields": fields,
                             "encoding": {"dtype": "float32", "missing": "nan"}},
                "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": rel,
                            "media_type": "application/octet-stream", "sha256": dig,
                            "bytes": path.stat().st_size}],
            })
    return frames


def refresh(max_leads: int | None = None) -> dict:
    ini = probe_latest()
    if ini is None:
        err = IngestError("NO_CYCLE", "未找到可用 GEFS 起报批次")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    max_leads = max_leads if max_leads is not None else get_settings().gefs_lead_max_hours
    leads = list(range(0, max_leads + 1, 3))
    decoded: dict[tuple[str, str], dict] = {}
    try:
        for lead in leads:
            for kind in ("geavg", "gespr"):
                path = _staged_path(ini, lead, kind)
                if not path.exists():
                    path = download(ini, lead, kind)
                decoded[(kind, to_iso(ini + timedelta(hours=lead)))] = decode_messages(path)
        frames = build_frames(ini, {}, {}, leads, by_valid=decoded)
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}

    snap_id = f"noaa-gefs-{ini:%Y%m%dT%H%M}Z"
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast",
                        "NOAA GEFS 0.5° 集合均值/离散度（概率为高斯近似）",
                        "NOAA NCEP", "https://www.nco.ncep.noaa.gov/pmb/products/gens/")
    active = repo.get_active_snapshot(DATASET_ID)
    publish = not (active and active.get("init_time") and to_iso(ini) < active["init_time"])
    snapshot = {"snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": to_iso(ini),
                "init_time": to_iso(ini), "payload_version": "1", "state": "published",
                "published_at": to_iso(datetime.now(timezone.utc)),
                "details": {"leads": leads, "source_url": FILTER_URL,
                            "note": "wind_prob 为基于集合均值/离散度的高斯近似，不是成员计数概率"}}
    repo.insert_snapshot(snapshot, frames, publish=publish)
    mark_success(SOURCE_ID, {"init_time": to_iso(ini), "frames": len(frames), "publish": publish})
    return {"ok": True, "snapshot_id": snap_id, "init_time": to_iso(ini),
            "frames": len(frames), "leads": leads, "publish": publish}
