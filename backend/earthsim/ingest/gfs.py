"""NOAA GFS 0.25 adapter.

Strategy (guide section 3.2): probe cycles newest-first, fetch a GRIB Filter
subset, validate every message with ecCodes, normalize to the shared grid for
the requested layers, then publish only a complete batch. Decoding is isolated
so it can be unit-tested with an injected decoder when ecCodes is unavailable.
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
from ..fields.timeutil import gfs_cycles, normalize_lon, to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "noaa_gfs"
DATASET_ID = "noaa-gfs"
FILTER_URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"
S3_BASE = "https://noaa-gfs-pds.s3.amazonaws.com"

# layer -> (accepted shortNames from the real GRIB Filter, typeOfLevel, level).
# Verified against a live 2026-11-20 12Z f000 subset with ecCodes 2.50.1:
#   10u, 10v (10 m wind), 2t, 2r (2 m), prmsl (meanSea), vis (surface, paramId 3020).
# IMPORTANT: the "t" message at surface is paramId=130 air_temperature (K),
# NOT total cloud cover. Do not map it to cloud_total. TCDC must be `tcc` at
# the atmosphere level. If upstream omits it, the layer is simply not published.
FIELD_MAP: dict[str, tuple[tuple[str, ...], str, float]] = {
    "wind10": (("10u", "10v", "u", "v", "UGRD", "VGRD"), "heightAboveGround", 10),
    "temp2m": (("2t", "TMP"), "heightAboveGround", 2),
    "rh2m": (("2r", "RH"), "heightAboveGround", 2),
    "dewpoint2m": (("2d", "DPT"), "heightAboveGround", 2),
    "mslp": (("prmsl", "msl", "PRMSL"), "meanSea", 0),
    "cloud_total": (("tcc", "TCDC"), "atmosphere", 0),
    "visibility_sfc": (("vis", "VIS"), "surface", 0),
    "precip": (("tp", "APCP"), "surface", 0),
    "snow_depth": (("sde", "SNOD"), "surface", 0),
    "surface_pressure": (("sp", "PRES"), "surface", 0),
    "cape": (("cape", "CAPE"), "surface", 0),
    "cin": (("cin", "CIN"), "surface", 0),
    "gh500": (("gh",), "isobaricInhPa", 500),
    "vvel500": (("w",), "isobaricInhPa", 500),
    # 500 hPa wind (already present in the 500mb subset) — upper-air ribbon source.
    "wind500": (("u", "v"), "isobaricInhPa", 500),
}
# Per-layer display metadata (unit, level, palette) — independent of source.
LAYER_META: dict[str, dict] = {
    "wind10": {"level": {"type": "height_agl", "value": 10, "unit": "m"}, "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}]},
    "temp2m": {"level": {"type": "height_agl", "value": 2, "unit": "m"}, "fields": [{"id": "temp", "unit": "K"}]},
    "rh2m": {"level": {"type": "height_agl", "value": 2, "unit": "m"}, "fields": [{"id": "rh", "unit": "%"}]},
    "dewpoint2m": {"level": {"type": "height_agl", "value": 2, "unit": "m"}, "fields": [{"id": "dewpoint", "unit": "K"}]},
    "mslp": {"level": {"type": "mean_sea_level", "value": 0, "unit": "Pa"}, "fields": [{"id": "mslp", "unit": "Pa"}]},
    "cloud_total": {"level": {"type": "atmosphere", "value": 0, "unit": ""}, "fields": [{"id": "cloud", "unit": "%"}]},
    "visibility_sfc": {"level": {"type": "surface", "value": 0, "unit": ""}, "fields": [{"id": "vis", "unit": "m"}]},
    "precip": {"level": {"type": "surface", "value": 0, "unit": ""}, "fields": [{"id": "precip", "unit": "mm"}]},
    "snow_depth": {"level": {"type": "surface", "value": 0, "unit": ""}, "fields": [{"id": "snow", "unit": "m"}]},
    "surface_pressure": {"level": {"type": "surface", "value": 0, "unit": ""}, "fields": [{"id": "pres", "unit": "Pa"}]},
    "cape": {"level": {"type": "surface", "value": 0, "unit": ""}, "fields": [{"id": "cape", "unit": "J/kg"}]},
    "cin": {"level": {"type": "surface", "value": 0, "unit": ""}, "fields": [{"id": "cin", "unit": "J/kg"}]},
    "gh500": {"level": {"type": "isobaric_in_hpa", "value": 500, "unit": "hPa"}, "fields": [{"id": "gh", "unit": "m2/s2"}]},
    "vvel500": {"level": {"type": "isobaric_in_hpa", "value": 500, "unit": "hPa"}, "fields": [{"id": "omega", "unit": "Pa/s"}]},
    "wind500": {"level": {"type": "isobaric_in_hpa", "value": 500, "unit": "hPa"}, "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}]},
}
# Core layers must be present for a batch to be usable. Others are optional.
CORE_LAYERS = {"wind10", "temp2m", "rh2m", "mslp"}
# Contract: row 0 = south pole (-90), col 0 = antimeridian (-180). GRIB native
# order is north-to-south / 0..360, so decode_messages() flips and rolls to this.
GFS_GRID = gmod.GridSpec("EPSG:4326", nx=1441, ny=721, lon0=-180.0, lat0=-90.0,
                         dx=0.25, dy=0.25, wrap_longitude=True)


def cycle_url(init: datetime, lead: int) -> str:
    ymd = init.strftime("%Y%m%d")
    cc = init.strftime("%H")
    return f"{S3_BASE}/gfs.{ymd}/{cc}/atmos/gfs.t{cc}z.pgrb2.0p25.f{lead:03d}"


# Requests are split into two staged files per lead so each stays small enough
# for the slow link: "core" (~13 MB) and "extra" (~2 MB). Requests with too many
# combined fields have been observed to hang server-side at NOMADS.
FIELD_GROUPS = ("core", "extra")


def filter_params(init: datetime, lead: int, group: str = "core") -> dict[str, str]:
    base = {
        "dir": f"/gfs.{init:%Y%m%d}/{init:%H}/atmos",
        "file": f"gfs.t{init:%H}z.pgrb2.0p25.f{lead:03d}",
    }
    if group == "extra":
        # Additional cheap surface fields; separate file keeps core small.
        base.update({
            "lev_surface": "on", "var_SNOD": "on", "var_PRES": "on", "var_CIN": "on",
        })
        return base
    base.update({
        "lev_10_m_above_ground": "on", "var_UGRD": "on", "var_VGRD": "on",
        "lev_2_m_above_ground": "on", "var_TMP": "on", "var_RH": "on", "var_DPT": "on",
        "lev_mean_sea_level": "on", "var_PRMSL": "on",
        # Note TCDC is NOT requested — NOMADS returns surface air temperature
        # (paramId 130) for var_TCDC on this endpoint, which would be mislabelled.
        "lev_surface": "on", "var_VIS": "on", "var_APCP": "on", "var_CAPE": "on",
        # upper-air at 500 hPa.
        "lev_500_mb": "on", "var_HGT": "on", "var_VVEL": "on",
    })
    return base


def probe_latest(now: datetime | None = None, attempts: int = 6) -> datetime | None:
    """Return the newest cycle whose f000 subset is actually available.

    M probing showed the NOMADS filter endpoint is reachable while HEAD against
    the public S3 mirror is frequently rejected, so availability is verified
    with a minimal GRIB Filter GET (only UGRD at 10 m).
    """
    import httpx
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        for init in gfs_cycles(now, attempts):
            probe_params = {
                "dir": f"/gfs.{init:%Y%m%d}/{init:%H}/atmos",
                "file": f"gfs.t{init:%H}z.pgrb2.0p25.f000",
                "lev_10_m_above_ground": "on", "var_UGRD": "on",
            }
            try:
                r = client.get(FILTER_URL, params=probe_params)
                if r.status_code == 200 and r.content[:4] == b"GRIB":
                    return init
            except httpx.HTTPError:
                continue
    return None


def _save_raw(init: datetime, lead: int, payload: bytes, group: str = "core") -> Path:
    root = get_settings().data_root
    name = "filter.grib2" if group == "core" else "filter-extra.grib2"
    rel = Path("raw/gfs") / f"{init:%Y%m%dT%H%M}Z" / f"f{lead:03d}" / name
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(payload)
    tmp.replace(path)
    return path


def validate_grib(payload: bytes) -> None:
    if len(payload) < 16 or payload[:4] != b"GRIB":
        raise IngestError("BAD_GRIB", "下载内容不是有效 GRIB 消息", {"len": len(payload)})


def download(init: datetime, lead: int, *, use_s3: bool = False, group: str = "core") -> Path:
    s = get_settings()
    if use_s3:
        r = fetch(cycle_url(init, lead), validator=lambda resp: validate_grib(resp.content))
    else:
        r = fetch(FILTER_URL, params=filter_params(init, lead, group),
                  validator=lambda resp: validate_grib(resp.content))
    if len(r.payload) > s.max_download_bytes:
        raise IngestError("SOURCE_TOO_LARGE", "GRIB 超过字节上限")
    return _save_raw(init, lead, r.payload, group)


def decode_messages(path: Path, *, decoder: Callable[[Path], dict] | None = None) -> dict:
    """Decode GRIB messages into arrays keyed by (layer, valid_time).

    Uses the optional ecCodes binding. ``decoder`` can be injected in tests.
    Returns ``{(layer, valid_time_iso): {field_name: ndarray(ny,nx)}}``.
    """
    if decoder is not None:
        return decoder(path)
    try:
        import eccodes  # type: ignore
    except ImportError as e:  # pragma: no cover - depends on deployment image
        raise IngestError("MISSING_ECODES", "未安装 ecCodes，无法解码 GRIB", {"hint": "pip install eccodes"}) from e

    out: dict[tuple[str, str], dict[str, np.ndarray]] = {}
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short = eccodes.codes_get(gid, "shortName")
                level_type = eccodes.codes_get(gid, "typeOfLevel")
                level = float(eccodes.codes_get(gid, "level"))
                step = int(eccodes.codes_get(gid, "forecastTime"))
                date = str(eccodes.codes_get(gid, "date"))
                htime = f"{int(eccodes.codes_get(gid, 'time')):04d}"
                init_dt = datetime.strptime(date + htime, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
                valid = to_iso(init_dt + timedelta(hours=step))
                # GRIB native order: row 0 = 90N (north-to-south), col 0 = 0E
                # (0..360). The project contract is south-to-north / -180..180,
                # so flip latitude then roll longitude by half the grid.
                values = eccodes.codes_get_values(gid).reshape(721, 1440)
                values = np.flipud(values)
                values = np.roll(values, 720, axis=1)
                rect = np.empty((GFS_GRID.ny, GFS_GRID.nx), dtype=np.float32)
                rect[:, :1440] = values
                rect[:, 1440] = values[:, 0]  # duplicate seam for wrap grid
                # GFS snow depth uses 9999 as a missing-value sentinel.
                if short in ("sde", "SNOD"):
                    rect[rect > 9000] = np.nan
                for layer, (want_names, want_type, want_level) in FIELD_MAP.items():
                    if short in want_names and level_type == want_type and float(level) == float(want_level):
                        out.setdefault((layer, valid), {})[short] = rect.astype(np.float32)
            finally:
                eccodes.codes_release(gid)
    return out


def build_frames(init: datetime, decoded: dict, leads: list[int]) -> list[dict]:
    """Turn decoded arrays into catalog frames; raises if a required field is absent."""
    snap_id = f"noaa-gfs-{init:%Y%m%dT%H%M}Z"
    frames: list[dict] = []
    for lead in leads:
        valid = to_iso(init + timedelta(hours=lead))
        for layer, meta in LAYER_META.items():
            key = (layer, valid)
            if key not in decoded:
                if layer in CORE_LAYERS:
                    raise IngestError("INCOMPLETE_BATCH", f"缺少核心字段 {layer} @{valid}", {"missing": layer})
                # Optional layer genuinely absent upstream: skip it instead of
                # publishing a mislabelled substitute.
                continue
            d = decoded[key]
            if layer in ("wind10", "wind500"):
                u = d.get("u", d.get("10u", d.get("UGRD")))
                v = d.get("v", d.get("10v", d.get("VGRD")))
                if u is None or v is None:
                    raise IngestError("INCOMPLETE_BATCH", "缺少风分量", {"valid": valid})
                arr = np.stack([u, v], axis=-1)
            else:
                first = next(iter(d.values()))
                arr = first[:, :, None]
            fid = f"{snap_id}-{layer}-f{lead:03d}"
            rel = f"derived/{snap_id}/{fid}.bin"
            root = get_settings().data_root
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            gmod.write_grid_binary(p, arr)
            dig = hashlib.sha256(p.read_bytes()).hexdigest()
            frames.append({
                "frame_id": fid, "layer_id": layer,
                "level_type": meta["level"]["type"], "level_value": float(meta["level"]["value"]),
                "valid_time": valid, "bbox": {"west": -180, "south": -90, "east": 180, "north": 90},
                "grid": GFS_GRID.to_dict(), "fields": meta["fields"],
                "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                             "kind": "forecast", "source_id": SOURCE_ID, "layer_id": layer,
                             "init_time": to_iso(init), "valid_time": valid,
                             "level": meta["level"], "grid": gmod.describe_grid(GFS_GRID),
                             "fields": meta["fields"],
                             "encoding": {"dtype": "float32", "missing": "nan"}},
                "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": rel,
                            "media_type": "application/octet-stream", "sha256": dig,
                            "bytes": p.stat().st_size}],
            })
    return frames


def _staged_path(init: datetime, lead: int, group: str = "core") -> Path:
    root = get_settings().data_root
    name = "filter.grib2" if group == "core" else "filter-extra.grib2"
    return root / "raw/gfs" / f"{init:%Y%m%dT%H%M}Z" / f"f{lead:03d}" / name


def refresh(max_leads: int | None = None) -> dict:
    """Probe, download, decode and publish a GFS batch.

    Already staged GRIB files are reused, so an interrupted collection resumes
    instead of re-downloading. When only a contiguous prefix completes, it is
    published as an explicitly labelled degraded timeline while the source
    status records the failure; an older active batch is never unseated by an
    incomplete candidate.
    """
    ini = probe_latest()
    if ini is None:
        err = IngestError("NO_CYCLE", "未找到可用 GFS 起报批次")
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
    max_leads = max_leads if max_leads is not None else get_settings().gfs_lead_max_hours
    decoded: dict = {}
    downloaded: list[int] = []
    missing: list[int] = []
    error: IngestError | None = None
    required = set(CORE_LAYERS)

    for lead in range(0, max_leads + 1):
        try:
            # Core group is mandatory; extra group is best-effort.
            core = _staged_path(ini, lead, "core")
            if not core.exists():
                core = download(ini, lead, group="core")
            else:
                validate_grib(core.read_bytes()[:16])
            decoded.update(decode_messages(core))
            extra = _staged_path(ini, lead, "extra")
            if not extra.exists():
                try:
                    extra = download(ini, lead, group="extra")
                except (IngestError, OSError):
                    extra = None  # optional fields: skip if download fails
            if extra and extra.exists():
                decoded.update(decode_messages(extra))
            downloaded.append(lead)
        except (IngestError, OSError) as e:
            error = e if isinstance(e, IngestError) else IngestError("DOWNLOAD_FAILED", str(e))
            missing = list(range(lead, max_leads + 1))
            break

    # A lead is usable only when every requested layer is present.
    complete = []
    for lead in downloaded:
        valid = to_iso(ini + timedelta(hours=lead))
        have = {layer for layer in required if (layer, valid) in decoded}
        if required - have:
            missing.append(lead)
        else:
            complete.append(lead)
    if not complete:
        err = error or IngestError("INCOMPLETE_BATCH", "没有任何完整时效", {"missing_lead_hours": missing})
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code, "init_time": to_iso(ini),
                "downloaded": downloaded, "missing_lead_hours": missing}

    try:
        frames = build_frames(ini, decoded, complete)
    except IngestError as e:
        mark_failure(SOURCE_ID, e)
        return {"ok": False, "error": e.code, "init_time": to_iso(ini)}

    snap_id = f"noaa-gfs-{ini:%Y%m%dT%H%M}Z"
    degraded = len(complete) < max_leads + 1
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast", "NOAA GFS 0.25 全球预报",
                        "NOAA NCEP", "https://www.nco.ncep.noaa.gov/pmb/products/gfs/")
    # A late-arriving older cycle must not unseat the active batch.
    active = repo.get_active_snapshot(DATASET_ID)
    publish = True
    if active and active.get("init_time") and to_iso(ini) < active["init_time"]:
        publish = False
    snapshot = {"snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": to_iso(ini),
                "init_time": to_iso(ini), "payload_version": "1", "state": "published",
                "published_at": to_iso(datetime.now(timezone.utc)),
                "details": {"leads": complete, "source_url": FILTER_URL,
                            "partial": degraded, "degraded_timeline": "3-hour" if degraded else None,
                            "missing_lead_hours": sorted(set(missing)),
                            "note": "仅包含已完成时效；超出覆盖端点标记缺测" if degraded else ""}}
    repo.insert_snapshot(snapshot, frames, publish=publish)
    if not publish:
        snapshot["details"]["staged_not_published"] = "older than active batch"
    if error or degraded:
        mark_failure(SOURCE_ID, error or IngestError("PARTIAL_BATCH", "部分时效已发布，其余仍在发布中",
                                                    {"missing_lead_hours": sorted(set(missing))}))
    else:
        mark_success(SOURCE_ID, {"init_time": to_iso(ini), "leads": len(complete)})
    return {"ok": True, "snapshot_id": snap_id, "init_time": to_iso(ini),
            "frames": len(frames), "leads": complete, "partial": degraded,
            "missing_lead_hours": sorted(set(missing)), "error": error.code if error else None}
