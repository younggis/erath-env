"""NOAA HRRR 3km regional model adapter for high-resolution data LOD.

HRRR CONUS is 3 km (~8x finer than GFS 0.25°). We fetch a small regional subset
via NOMADS GRIB Filter, decode 10 m U/V with ecCodes, reconstruct the Lambert
Conformal grid's lat/lon with pyproj, and resample to a regular EPSG:4326 grid
so the app can load finer data where available.
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

log = logging.getLogger(__name__)
SOURCE_ID = "noaa_hrrr"
DATASET_ID = "noaa-hrrr"
GRIB_FILTER = "https://nomads.ncep.noaa.gov/cgi-bin/filter_hrrr_sub.pl"

# HRRR Lambert Conformal projection constants (from GRIB metadata).
LCC_LON0 = -97.5
LCC_LAT1 = LCC_LAT2 = 38.5
DEFAULT_BBOX = (-100.0, 35.0, -80.0, 50.0)

# Regular 4326 output grid resolution for the resampled product.
OUT_DX = OUT_DY = 0.05  # ~5 km, close to the 3 km native resolution


def _cycle(when: datetime) -> tuple[str, str]:
    when = when.astimezone(timezone.utc)
    hh = (when.hour // 6) * 6
    return when.strftime("%Y%m%d"), f"{hh:02d}"


def _lcc_transformer():
    from pyproj import Transformer
    lcc = (f"+proj=lcc +lon_0={LCC_LON0} +lat_1={LCC_LAT1} +lat_2={LCC_LAT2} "
           f"+lat_0={LCC_LAT1} +datum=WGS84 +units=m +no_defs")
    return Transformer.from_crs(lcc, "EPSG:4326", always_xy=True)


def _decode_subset(path: Path) -> tuple[np.ndarray, dict]:
    """Decode 10m U/V from a HRRR Lambert subset GRIB into (values, grid dict)."""
    import eccodes
    u = v = None
    nx = ny = None
    lon1 = lat1 = dx = None
    with path.open("rb") as fh:
        while True:
            gid = eccodes.codes_grib_new_from_file(fh)
            if gid is None:
                break
            try:
                short = eccodes.codes_get(gid, "shortName")
                if short not in ("10u", "10v"):
                    continue
                if eccodes.codes_get(gid, "typeOfLevel") != "heightAboveGround":
                    continue
                nx = int(eccodes.codes_get(gid, "Ni")); ny = int(eccodes.codes_get(gid, "Nj"))
                lon1 = float(eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")) - 360
                lat1 = float(eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees"))
                dx = float(eccodes.codes_get(gid, "DxInMetres"))
                vals = np.asarray(eccodes.codes_get_values(gid), dtype=np.float32)
                if vals.size != nx * ny:
                    continue
                if short == "10u":
                    u = vals.reshape(ny, nx)
                else:
                    v = vals.reshape(ny, nx)
            finally:
                eccodes.codes_release(gid)
    if u is None or v is None:
        raise IngestError("NO_WIND", "HRRR 子集缺少 10m 风分量")

    # Reconstruct lat/lon of the Lambert grid (scanning: i east, j north).
    from pyproj import Transformer
    lcc = (f"+proj=lcc +lon_0={LCC_LON0} +lat_1={LCC_LAT1} +lat_2={LCC_LAT2} "
           f"+lat_0={LCC_LAT1} +datum=WGS84 +units=m +no_defs")
    to_xy = Transformer.from_crs("EPSG:4326", lcc, always_xy=True)
    to_ll = Transformer.from_crs(lcc, "EPSG:4326", always_xy=True)
    x0, y0 = to_xy.transform(lon1, lat1)
    xi = x0 + np.arange(nx) * dx
    yi = y0 + np.arange(ny) * dx
    XX, YY = np.meshgrid(xi, yi)
    LON, LAT = to_ll.transform(XX.ravel(), YY.ravel())
    LON = LON.reshape(ny, nx); LAT = LAT.reshape(ny, nx)

    # Resample to a regular 4326 grid covering the subset extent.
    w, e = float(LON.min()), float(LON.max())
    s, n = float(LAT.min()), float(LAT.max())
    gx = np.arange(w, e + OUT_DX, OUT_DX)
    gy = np.arange(s, n + OUT_DY, OUT_DY)
    GOX, GOY = np.meshgrid(gx, gy)
    # Scatter interpolation of u,v onto the regular grid via griddata.
    from scipy.interpolate import griddata
    pts = np.column_stack([LON.ravel(), LAT.ravel()])
    ug = griddata(pts, u.ravel(), (GOX, GOY), method="linear")
    vg = griddata(pts, v.ravel(), (GOX, GOY), method="linear")
    # Fill holes at edges with nearest.
    mask = ~np.isfinite(ug)
    if mask.any():
        un = griddata(pts, u.ravel(), (GOX, GOY), method="nearest")
        vn = griddata(pts, v.ravel(), (GOX, GOY), method="nearest")
        ug = np.where(mask, un, ug); vg = np.where(mask, vn, vg)
    values = np.stack([ug, vg], axis=-1).astype(np.float32)
    grid = gmod.GridSpec("EPSG:4326", len(gx), len(gy), float(gx[0]), float(gy[0]),
                         OUT_DX, OUT_DY, wrap_longitude=False).to_dict()
    return values, grid


def fetch_subset(bbox: tuple[float, float, float, float],
                 when: datetime | None = None) -> tuple[np.ndarray, dict]:
    """Fetch + decode HRRR 10m U/V for a bbox into a regular 4326 grid."""
    when = when or datetime.now(timezone.utc)
    date, hh = _cycle(when)
    west, south, east, north = bbox
    fname = f"hrrr.t{hh}z.wrfsubhf00.grib2"
    params = {
        "dir": f"/hrrr.{date}/conus", "file": fname,
        "lev_10_m_above_ground": "on", "var_UGRD": "on", "var_VGRD": "on",
        "subregion": "", "leftlon": str(int(np.floor(west))), "rightlon": str(int(np.ceil(east))),
        "toplat": str(int(np.ceil(north))), "bottomlat": str(int(np.floor(south))),
    }
    r = fetch(GRIB_FILTER, params=params, timeout=120)
    if r.payload[:4] != b"GRIB":
        raise IngestError("BAD_HRRR_GRIB", "HRRR 响应不是 GRIB", {"len": len(r.payload)})
    root = get_settings().data_root
    rel = f"raw/hrrr/{date}/{hh}/sub.grib2"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    tmp.write_bytes(r.payload)
    tmp.replace(p)
    return _decode_subset(p)


def refresh(when: datetime | None = None) -> dict:
    """Fetch HRRR for the default US region and publish as a 3km data layer."""
    try:
        values, gd = fetch_subset(DEFAULT_BBOX, when)
    except IngestError as e:
        log.warning("HRRR refresh failed: %s", e)
        mark_failure(SOURCE_ID, e)
        return {"ok": False, "error": e.code}
    snap_id = f"hrrr-{datetime.now(timezone.utc):%Y%m%dT%H%M}Z"
    root = get_settings().data_root
    rel = f"derived/{snap_id}/hrrr-wind10.bin"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    gmod.write_grid_binary(p, values)
    dig = hashlib.sha256(p.read_bytes()).hexdigest()
    sid = "hrrr-wind10"
    frame = {
        "frame_id": sid, "layer_id": "hrrr_wind10", "level_type": "height_agl",
        "level_value": 10, "valid_time": to_iso(when or datetime.now(timezone.utc)),
        "bbox": {"west": gd["lon0"], "south": gd["lat0"],
                 "east": gd["lon0"] + (gd["nx"] - 1) * gd["dx"],
                 "north": gd["lat0"] + (gd["ny"] - 1) * gd["dy"]},
        "grid": gd,
        "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}],
        "manifest": {"schema_version": 1, "frame_id": sid, "snapshot_id": snap_id,
                     "kind": "forecast", "source_id": SOURCE_ID, "layer_id": "hrrr_wind10",
                     "resolution_km": 3, "grid": gmod.describe_grid(gmod.GridSpec.from_dict(gd)),
                     "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}],
                     "encoding": {"dtype": "float32", "missing": "nan"}},
        "assets": [{"asset_id": sid + "-bin", "role": "grid", "relative_path": rel,
                    "media_type": "application/octet-stream", "sha256": dig, "bytes": p.stat().st_size}],
    }
    snapshot = {
        "snapshot_id": snap_id, "dataset_id": DATASET_ID, "identity_key": snap_id,
        "payload_version": "1", "state": "published",
        "published_at": to_iso(datetime.now(timezone.utc)),
        "details": {"resolution_km": 3, "bbox": frame["bbox"], "source": "NOAA HRRR CONUS"},
    }
    repo.ensure_dataset(DATASET_ID, SOURCE_ID, "forecast", "NOAA HRRR 3km 区域风场",
                        "NOAA NCEP", "https://nomads.ncep.noaa.gov/")
    repo.insert_snapshot(snapshot, [frame], publish=True)
    mark_success(SOURCE_ID, {"snapshot_id": snap_id, "resolution_km": 3})
    return {"ok": True, "snapshot_id": snap_id, "grid": gd}
