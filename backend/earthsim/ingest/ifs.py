"""ECMWF IFS open-data adapter (AWS S3 mirror, CC-BY-4.0).

IFS 0.25° oper GRIB2 files (~98 MB) contain a rich parameter set that
complements GFS: low/mid/high cloud cover, soil moisture/temperature,
total-column water, radiation, 100 m wind, wave height and more. We download
one file per cycle in the background, decode the selected surface fields with
ecCodes and publish them as an independent forecast dataset for comparison.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from ..config import get_settings
from ..fields import grid as gmod
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)
SOURCE_ID = "ecmwf_ifs"
DATASET_ID = "ecmwf-ifs"
S3 = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"

# IFS 0.25° is a regular 1440x721 grid. GRIB native order is north-to-south
# with col 0 at 180E (= -180); after flipping to south-to-north col 0 is -180.
IFS_GRID = gmod.GridSpec("EPSG:4326", 1441, 721, -180.0, -90.0, 0.25, 0.25, wrap_longitude=True)

# layer -> shortName ; field contract for the surface parameters we publish.
# Verified from the ECMWF open-data parameter list (surface 'sfc' level).
FIELDS: dict[str, tuple[str, str, str, str]] = {
    # layer: (shortName, unit, display_unit, palette)
    "ifs_2t": ("2t", "K", "°C", "temperature"),
    "ifs_2d": ("2d", "K", "°C", "temperature"),
    "ifs_msl": ("msl", "Pa", "hPa", "pressure"),
    "ifs_10u": ("10u", "m/s", "m/s", "wind"),
    "ifs_10v": ("10v", "m/s", "m/s", "wind"),
    "ifs_tcc": ("tcc", "%", "%", "cloud"),
    "ifs_lcc": ("lcc", "%", "%", "cloud"),
    "ifs_mcc": ("mcc", "%", "%", "cloud"),
    "ifs_hcc": ("hcc", "%", "%", "cloud"),
    "ifs_tp": ("tp", "m", "mm", "precip"),
    "ifs_sd": ("sd", "m", "cm", "snow"),
    "ifs_tcwv": ("tcwv", "kg/m2", "kg/m2", "humidity"),
    "ifs_ssrd": ("ssrd", "J/m2", "MJ/m2", "cape"),
    "ifs_100u": ("100u", "m/s", "m/s", "wind"),
    "ifs_100v": ("100v", "m/s", "m/s", "wind"),
}


def file_url(init: datetime) -> str:
    ymd = init.strftime("%Y%m%d")
    hh = init.strftime("%H")
    stamp = f"{ymd}{hh}0000"
    return f"{S3}/{ymd}/{hh}z/ifs/0p25/oper/{stamp}-0h-oper-fc.grib2"


def probe_latest(now: datetime | None = None, attempts: int = 4) -> datetime | None:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    import httpx
    with httpx.Client(timeout=20, follow_redirects=True) as c:
        for i in range(attempts):
            init = base - timedelta(hours=6 * i)
            try:
                r = c.head(file_url(init))
                if r.status_code == 200:
                    return init
            except httpx.HTTPError:
                continue
    return None


def _decode(path: Path, valid: str, init: datetime) -> list[dict]:
    """Decode selected surface fields from an IFS GRIB2 file into frames."""
    import eccodes
    root = get_settings().data_root
    snap_id = f"ifs-{init:%Y%m%dT%H%M}Z"
    found: dict[str, np.ndarray] = {}
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short = eccodes.codes_get(gid, "shortName")
                lt = eccodes.codes_get(gid, "typeOfLevel")
                step = int(eccodes.codes_get(gid, "forecastTime"))
                if step != 0 or lt != "surface":
                    continue
                layer = next((k for k, v in FIELDS.items() if v[0] == short), None)
                if not layer:
                    continue
                vals = np.asarray(eccodes.codes_get_values(gid), dtype=np.float32)
                if vals.size != 1440 * 721:
                    continue
                # GRIB native: row 0 = 90N, col 0 = 180E (= -180). Flip to
                # south-to-north; no longitude roll needed (col 0 already -180).
                vals = np.flipud(vals.reshape(721, 1440))
                # ECMWF cloud cover is a 0..1 fraction; project contract is %.
                if layer in ("ifs_tcc", "ifs_lcc", "ifs_mcc", "ifs_hcc"):
                    vals = vals * 100.0
                rect = np.empty((721, 1441), dtype=np.float32)
                rect[:, :1440] = vals; rect[:, 1440] = vals[:, 0]
                # Accumulation fields are identically zero at f000 — publishing
                # them yields a permanently empty layer. Skip until a later lead.
                if layer in ("ifs_tp", "ifs_ssrd") and not np.any(rect > 0):
                    continue
                found[layer] = rect
            finally:
                eccodes.codes_release(gid)
    frames = []
    for layer, arr in found.items():
        unit, _, palette = FIELDS[layer][1], FIELDS[layer][2], FIELDS[layer][3]
        fid = f"{snap_id}-{layer}"
        rel = f"derived/{snap_id}/{fid}.bin"
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        gmod.write_grid_binary(p, arr[:, :, None].astype(np.float32))
        dig = hashlib.sha256(p.read_bytes()).hexdigest()
        frames.append({
            "frame_id": fid, "layer_id": layer, "level_type": "surface", "level_value": 0,
            "valid_time": valid, "bbox": {"west": -180, "south": -90, "east": 180, "north": 90},
            "grid": IFS_GRID.to_dict(), "fields": [{"id": layer, "unit": unit}],
            "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                         "kind": "forecast", "source_id": SOURCE_ID, "layer_id": layer,
                         "init_time": to_iso(init), "valid_time": valid,
                         "grid": gmod.describe_grid(IFS_GRID), "fields": [{"id": layer, "unit": unit}],
                         "palette": palette,
                         "encoding": {"dtype": "float32", "missing": "nan"}},
            "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": rel,
                        "media_type": "application/octet-stream", "sha256": dig, "bytes": p.stat().st_size}],
        })
    return frames


def _download_resumable(url: str, target: Path, *, timeout: float = 120) -> None:
    """Stream a large GRIB to ``target`` with Range-based resume + progress log.

    ``base.fetch`` buffers the whole payload in memory, which is unsuitable for
    the ~98 MB IFS file on a slow link.  Here we append directly to a ``.part``
    file so the download survives interrupts and progress is observable.
    """
    import httpx
    s = get_settings()
    part = target.with_suffix(".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "earthsim/1.0 (local research simulator)"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    log.info("IFS download start url=%s offset=%d MB", url, offset // 1048576)
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            with client.stream("GET", url) as r:
                if r.status_code == 416:  # nothing left to resume
                    part.replace(target)
                    return
                if r.status_code not in (200, 206):
                    raise IngestError("SOURCE_ERROR", f"IFS 下载返回 {r.status_code}", {"url": url})
                if r.status_code == 200 and offset:
                    log.warning("IFS 源不支持 Range，从头下载")
                    offset = 0
                total = offset
                cr = r.headers.get("content-range")
                if cr and "/" in cr:
                    try:
                        total = int(cr.split("/")[-1])
                    except ValueError:
                        pass
                elif r.headers.get("content-length"):
                    total = offset + int(r.headers["content-length"])
                if total > s.max_download_bytes:
                    raise IngestError("SOURCE_TOO_LARGE", "IFS 文件超过字节上限", {"bytes": total})
                mode = "ab" if offset else "wb"
                next_log = offset + 10 * 1048576
                with part.open(mode) as fh:
                    for chunk in r.iter_bytes(chunk_size=262144):
                        fh.write(chunk)
                        total_seen = fh.tell()  # in append mode tell() already includes existing bytes
                        if total_seen >= next_log:
                            log.info("IFS download %.1f / %.1f MB", total_seen / 1048576, total / 1048576)
                            next_log += 10 * 1048576
        if part.stat().st_size < 1024 or part.open("rb").read(4) != b"GRIB":
            raise IngestError("BAD_IFS_GRIB", "IFS 响应不是 GRIB")
        part.replace(target)
        log.info("IFS download done %.1f MB", target.stat().st_size / 1048576)
    except httpx.HTTPError as e:
        raise IngestError("NETWORK_ERROR", f"IFS 下载失败：{e}", {"error": str(e)}) from e


def refresh() -> dict:
    init = probe_latest()
    if init is None:
        err = IngestError("NO_IFS_CYCLE", "未找到可用 IFS 起报批次")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    url = file_url(init)
    root = get_settings().data_root
    rel = f"raw/ifs/{init:%Y%m%dT%H%M}Z/oper.grib2"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if not p.exists():
        try:
            _download_resumable(url, p)
        except IngestError as e:
            mark_failure(SOURCE_ID, e)
            return {"ok": False, "error": e.code}
    snap_id = f"ifs-{init:%Y%m%dT%H%M}Z"
    frames = _decode(p, to_iso(init), init)
    if not frames:
        err = IngestError("NO_FIELDS", "IFS 文件未解码出目标字段")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    snapshot = {"snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": snap_id,
                "init_time": to_iso(init), "payload_version": "1", "state": "published",
                "published_at": to_iso(datetime.now(timezone.utc)),
                "details": {"source": "ECMWF IFS open data (AWS)", "resolution_deg": 0.25,
                            "license": "CC-BY-4.0", "fields": [f["layer_id"] for f in frames]}}
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast", "ECMWF IFS 全球预报（开放数据）",
                        "ECMWF", "https://www.ecmwf.int/en/forecasts/datasets/open-data")
    repo.insert_snapshot(snapshot, frames, publish=True)
    mark_success(SOURCE_ID, {"snapshot_id": snap_id, "frames": len(frames)})
    return {"ok": True, "snapshot_id": snap_id, "frames": len(frames),
            "fields": [f["layer_id"] for f in frames]}
