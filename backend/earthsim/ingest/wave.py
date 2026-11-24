"""NOAA GFS-Wave 0.25° global wave adapter.

The NOMADS wave filter returns one GRIB file per lead with significant wave
height (swh), peak period (perpw) and mean direction (dirpw). Decode uses the
same south-to-north / -180..180 grid contract as GFS. A visual-only drift
vector is derived from the reported wave direction for particle rendering;
the scalar source fields stay unmodified.
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
from ..fields.timeutil import gfs_cycles, to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "noaa_wave"
DATASET_ID = "noaa-wave"
FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfswave.pl"

WAVE_GRID = gmod.GridSpec("EPSG:4326", nx=1441, ny=721, lon0=-180.0, lat0=-90.0,
                          dx=0.25, dy=0.25, wrap_longitude=True)
FIELD_MAP = {"wave_height": "swh", "wave_period": "perpw", "wave_direction": "dirpw"}
LAYER_META = {
    "wave_height": {"level": {"type": "surface", "value": 0, "unit": ""},
                    "fields": [{"id": "wave_height", "unit": "m"}]},
    "wave_period": {"level": {"type": "surface", "value": 0, "unit": ""},
                    "fields": [{"id": "wave_period", "unit": "s"}]},
    "wave_direction": {"level": {"type": "surface", "value": 0, "unit": ""},
                       "fields": [{"id": "wave_direction", "unit": "degree"}]},
    "wave_drift": {"level": {"type": "surface", "value": 0, "unit": ""},
                   "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}]},
}
BBOX = {"west": -180, "south": -90, "east": 180, "north": 90}


def filter_params(init: datetime, lead: int) -> dict[str, str]:
    return {
        "dir": f"/gfs.{init:%Y%m%d}/{init:%H}/wave/gridded",
        "file": f"gfswave.t{init:%H}z.global.0p25.f{lead:03d}.grib2",
        "var_HTSGW": "on", "var_PERPW": "on", "var_DIRPW": "on",
    }


def validate_grib(payload: bytes) -> None:
    if len(payload) < 16 or payload[:4] != b"GRIB":
        raise IngestError("BAD_GRIB", "下载内容不是有效 GRIB 消息", {"len": len(payload)})


def probe_latest(now: datetime | None = None, attempts: int = 6) -> datetime | None:
    import httpx
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for init in gfs_cycles(now, attempts):
            params = filter_params(init, 0)
            params.pop("var_PERPW"); params.pop("var_DIRPW")
            try:
                r = client.get(FILTER_URL, params=params)
                if r.status_code == 200 and r.content[:4] == b"GRIB":
                    return init
            except httpx.HTTPError:
                continue
    return None


def _staged_path(init: datetime, lead: int) -> Path:
    root = get_settings().data_root
    return root / "raw/gfs-wave" / f"{init:%Y%m%dT%H%M}Z" / f"f{lead:03d}" / "filter.grib2"


def download(init: datetime, lead: int) -> Path:
    s = get_settings()
    result = fetch(FILTER_URL, params=filter_params(init, lead),
                   validator=lambda resp: validate_grib(resp.content))
    if len(result.payload) > s.max_download_bytes:
        raise IngestError("SOURCE_TOO_LARGE", "GRIB 超过字节上限")
    path = _staged_path(init, lead)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(result.payload)
    tmp.replace(path)
    return path


def decode_messages(path: Path, *, decoder: Callable[[Path], dict] | None = None) -> dict:
    """Return ``{(layer, valid_time): {shortName: ndarray(ny,nx)}}``."""
    if decoder is not None:
        return decoder(path)
    try:
        import eccodes  # type: ignore
    except ImportError as e:  # pragma: no cover
        raise IngestError("MISSING_ECODES", "未安装 ecCodes，无法解码 GRIB", {"hint": "pip install eccodes"}) from e

    out: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short = str(eccodes.codes_get(gid, "shortName"))
                if short not in FIELD_MAP.values():
                    continue
                step = int(eccodes.codes_get(gid, "forecastTime"))
                date = str(eccodes.codes_get(gid, "date"))
                htime = f"{int(eccodes.codes_get(gid, 'time')):04d}"
                init_dt = datetime.strptime(date + htime, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                valid = to_iso(init_dt + timedelta(hours=step))
                # Native wave grid: 1440x721, north-to-south / 0..360.
                values = eccodes.codes_get_values(gid).reshape(721, 1440)
                values = np.roll(np.flipud(values), 720, axis=1)
                rect = np.empty((WAVE_GRID.ny, WAVE_GRID.nx), dtype=np.float32)
                rect[:, :1440] = values
                rect[:, 1440] = values[:, 0]
                # Upstream uses large sentinels for land/no-data.
                rect[rect > 9000] = np.nan
                layer = next(k for k, v in FIELD_MAP.items() if v == short)
                out.setdefault((layer, valid), {})[short] = rect.astype(np.float32)
            finally:
                eccodes.codes_release(gid)
    return out


def build_frames(init: datetime, decoded: dict, leads: list[int]) -> list[dict]:
    snap_id = f"noaa-wave-{init:%Y%m%dT%H%M}Z"
    frames: list[dict] = []
    for lead in leads:
        valid = to_iso(init + timedelta(hours=lead))
        height = decoded.get(("wave_height", valid), {}).get("swh")
        if height is None:
            raise IngestError("INCOMPLETE_BATCH", f"缺少有效波高 @{valid}")
        period = decoded.get(("wave_period", valid), {}).get("perpw")
        direction = decoded.get(("wave_direction", valid), {}).get("dirpw")
        arrays = {
            "wave_height": height[:, :, None],
            "wave_period": (period if period is not None else np.full_like(height, np.nan))[:, :, None],
            "wave_direction": (direction if direction is not None else np.full_like(height, np.nan))[:, :, None],
        }
        if direction is not None:
            # Oceanographic direction is where waves come FROM; propagation is
            # the opposite. Amplitude is only a visual speed proxy, not physics.
            amp = np.clip(height * 0.35, 0, 8)
            rad = np.deg2rad(direction)
            arrays["wave_drift"] = np.stack([-np.sin(rad) * amp, -np.cos(rad) * amp], axis=-1).astype(np.float32)
        for layer, arr in arrays.items():
            fid = f"{snap_id}-{layer}-f{lead:03d}"
            rel = f"derived/{snap_id}/{fid}.bin"
            path = get_settings().data_root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            gmod.write_grid_binary(path, arr)
            dig = hashlib.sha256(path.read_bytes()).hexdigest()
            meta = LAYER_META[layer]
            frames.append({
                "frame_id": fid, "layer_id": layer,
                "level_type": meta["level"]["type"], "level_value": 0.0,
                "valid_time": valid, "bbox": BBOX,
                "grid": WAVE_GRID.to_dict(), "fields": meta["fields"],
                "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                             "kind": "forecast", "source_id": SOURCE_ID, "layer_id": layer,
                             "init_time": to_iso(init), "valid_time": valid,
                             "level": meta["level"], "grid": gmod.describe_grid(WAVE_GRID),
                             "fields": meta["fields"],
                             "encoding": {"dtype": "float32", "missing": "nan"}},
                "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": rel,
                            "media_type": "application/octet-stream", "sha256": dig,
                            "bytes": path.stat().st_size}],
            })
    return frames


def refresh(max_leads: int | None = None) -> dict:
    ini = probe_latest()
    if ini is None:
        err = IngestError("NO_CYCLE", "未找到可用 GFS-Wave 起报批次")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    max_leads = max_leads if max_leads is not None else get_settings().wave_lead_max_hours
    decoded: dict = {}
    complete: list[int] = []
    error: IngestError | None = None
    for lead in range(0, max_leads + 1):
        try:
            path = _staged_path(ini, lead)
            if not path.exists():
                path = download(ini, lead)
            else:
                validate_grib(path.read_bytes()[:16])
            decoded.update(decode_messages(path))
            if ("wave_height", to_iso(ini + timedelta(hours=lead))) in decoded:
                complete.append(lead)
        except (IngestError, OSError) as e:
            error = e if isinstance(e, IngestError) else IngestError("DOWNLOAD_FAILED", str(e))
            break
    if not complete:
        err = error or IngestError("INCOMPLETE_BATCH", "没有任何完整波场时效")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    frames = build_frames(ini, decoded, complete)
    snap_id = f"noaa-wave-{ini:%Y%m%dT%H%M}Z"
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast", "NOAA GFS-Wave 0.25 全球海浪",
                        "NOAA NCEP", "https://nomads.ncep.noaa.gov/")
    active = repo.get_active_snapshot(DATASET_ID)
    publish = not (active and active.get("init_time") and to_iso(ini) < active["init_time"])
    snapshot = {"snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": to_iso(ini),
                "init_time": to_iso(ini), "payload_version": "1", "state": "published",
                "published_at": to_iso(datetime.now(timezone.utc)),
                "details": {"leads": complete, "source_url": FILTER_URL,
                            "partial": len(complete) < max_leads + 1,
                            "note": "wave_drift 为波向换算的可视化传播矢量，非真实海流"}}
    repo.insert_snapshot(snapshot, frames, publish=publish)
    if error:
        mark_failure(SOURCE_ID, error)
    else:
        mark_success(SOURCE_ID, {"init_time": to_iso(ini), "leads": len(complete)})
    return {"ok": True, "snapshot_id": snap_id, "init_time": to_iso(ini),
            "frames": len(frames), "leads": complete, "publish": publish,
            "error": error.code if error else None}
