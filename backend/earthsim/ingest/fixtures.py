"""Deterministic, fully offline fixture generator.

Every fixture is synthetic and labelled ``kind=fixture`` / ``source=demo``.
Fields are smooth analytic functions so unit tests can assert exact sample
values. Install is idempotent: files are rewritten deterministically and the
catalog rows use stable IDs.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ..config import get_settings
from ..catalog import repository as repo
from ..fields import grid as gmod
from ..fields.timeutil import to_iso

UTC = timezone.utc

GFS_DATASET = "demo-gfs"
METAR_DATASET = "demo-metar"
DEM_DATASET = "demo-dem"

GRID = gmod.GridSpec("EPSG:4326", nx=181, ny=91, lon0=-180.0, lat0=-90.0,
                     dx=2.0, dy=2.0, wrap_longitude=True)

LAYER_META: dict[str, dict] = {
    "wind10": {"level": {"type": "height_agl", "value": 10, "unit": "m"}, "ncomp": 2,
               "fields": [{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}]},
    "temp2m": {"level": {"type": "height_agl", "value": 2, "unit": "m"}, "ncomp": 1,
               "fields": [{"id": "temp", "unit": "K"}]},
    "rh2m": {"level": {"type": "height_agl", "value": 2, "unit": "m"}, "ncomp": 1,
             "fields": [{"id": "rh", "unit": "%"}]},
    "mslp": {"level": {"type": "mean_sea_level", "value": 0, "unit": "Pa"}, "ncomp": 1,
             "fields": [{"id": "mslp", "unit": "Pa"}]},
    "cloud_total": {"level": {"type": "atmosphere", "value": 0, "unit": ""}, "ncomp": 1,
                    "fields": [{"id": "cloud", "unit": "%"}]},
    "visibility_sfc": {"level": {"type": "surface", "value": 0, "unit": ""}, "ncomp": 1,
                       "fields": [{"id": "vis", "unit": "m"}]},
}


def analytic_field(name: str, lon: np.ndarray, lat: np.ndarray, t: float) -> np.ndarray:
    """Smooth reference fields; ``t`` is forecast lead in hours."""
    L = np.deg2rad(lon)
    P = np.deg2rad(lat)
    if name == "u":
        return 8.0 * np.sin(P) + 3.0 * np.cos(2 * L + t / 6.0)
    if name == "v":
        return 4.0 * np.cos(P) * np.sin(L + t / 8.0)
    if name == "temp":
        return 273.15 + 30.0 * np.cos(P) - 5.0 * np.sin(L + t / 12.0)
    if name == "rh":
        return np.clip(50.0 + 30.0 * np.sin(2 * P + t / 10.0), 5.0, 100.0)
    if name == "mslp":
        return 101325.0 + 1500.0 * np.sin(2 * L) * np.cos(P)
    if name == "cloud":
        return np.clip(40.0 + 40.0 * np.sin(3 * L + 2 * P + t / 9.0), 0.0, 100.0)
    if name == "vis":
        return np.clip(9000.0 + 7000.0 * np.cos(2 * L - 3 * P + t / 15.0), 0.0, 20000.0)
    raise KeyError(name)


def _rel_write(rel: str, data: bytes) -> dict:
    root = get_settings().data_root
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(path)
    return {"relative_path": rel, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


# --------------------------------------------------------------------------- GFS
def install_gfs(init: datetime | None = None, leads: list[int] | None = None) -> dict:
    init = init or datetime(2026, 11, 20, 0, 0, 0, tzinfo=UTC)
    leads = leads if leads is not None else list(range(0, 25))
    init_s = to_iso(init)
    snap_id = f"fixture-gfs-{init:%Y%m%dT%H%M}Z"
    lons, lats = GRID.lons(), GRID.lats()
    LON, LAT = np.meshgrid(lons, lats)
    frames: list[dict] = []

    for lead in leads:
        valid = to_iso(init + timedelta(hours=lead))
        for layer, meta in LAYER_META.items():
            ncomp = meta["ncomp"]
            arr = np.empty((GRID.ny, GRID.nx, ncomp), dtype="<f4")
            if layer == "wind10":
                arr[:, :, 0] = analytic_field("u", LON, LAT, lead)
                arr[:, :, 1] = analytic_field("v", LON, LAT, lead)
            else:
                field_name = {"temp2m": "temp", "rh2m": "rh", "mslp": "mslp",
                              "cloud_total": "cloud", "visibility_sfc": "vis"}[layer]
                arr[:, :, 0] = analytic_field(field_name, LON, LAT, lead)
            # Deterministic missing patch in visibility (tests NaN handling).
            if layer == "visibility_sfc":
                arr[36:41, 90:96, 0] = np.nan
            fid = f"fixture-{layer}-t{lead:02d}"
            rel = f"derived/{snap_id}/{fid}.bin"
            a = _rel_write(rel, arr.tobytes(order="C"))
            frame = {
                "frame_id": fid,
                "layer_id": layer,
                "level_type": meta["level"]["type"],
                "level_value": float(meta["level"]["value"]),
                "valid_time": valid,
                "bbox": {"west": -180, "south": -90, "east": 180, "north": 90},
                "grid": GRID.to_dict(),
                "fields": meta["fields"],
                "manifest": {
                    "schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                    "kind": "fixture", "source_id": "demo", "layer_id": layer,
                    "init_time": init_s, "valid_time": valid, "received_at": None,
                    "level": meta["level"],
                    "grid": gmod.describe_grid(GRID),
                    "fields": meta["fields"],
                    "encoding": {"dtype": "float32", "byte_order": "little",
                                 "layout": "y_x_component_interleaved" if ncomp == 2 else "y_x",
                                 "missing": "nan"},
                },
                "assets": [{"asset_id": fid + "-bin", "role": "grid",
                            "relative_path": a["relative_path"], "media_type": "application/octet-stream",
                            "sha256": a["sha256"], "bytes": a["bytes"]}],
            }
            frames.append(frame)

    snapshot = {
        "snapshot_id": snap_id, "dataset_id": GFS_DATASET,
        "identity_key": init_s, "init_time": init_s,
        "payload_version": "1", "state": "published", "published_at": init_s,
        "details": {"kind": "fixture", "grid": GRID.to_dict(), "leads": leads,
                    "note": "解析函数生成的演示场，非真实观测"},
    }
    repo.ensure_dataset(GFS_DATASET, "demo", "fixture",
                        "演示全球预报场（解析函数生成）", "EarthSim fixture", "")
    repo.insert_snapshot(snapshot, frames, publish=True)
    repo.upsert_source("demo", success=True, at=init_s, details={"kind": "fixture"})
    return {"snapshot_id": snap_id, "frames": len(frames)}


# --------------------------------------------------------------------------- METAR
STATIONS = [
    ("RJTT", 139.7798, 35.5494), ("RJCC", 141.4347, 43.0343),
    ("RKSI", 126.4505, 37.4602), ("ZSPD", 121.8052, 31.1443),
    ("WSSS", 103.9915, 1.3644), ("VHHH", 113.9147, 22.3089),
    # Alpine stations used by the regional case verification (synthetic coords).
    ("LIMC", 7.45, 45.60), ("LSZH", 7.80, 45.90), ("LOWI", 7.20, 46.10),
]


def install_metar() -> dict:
    snap_id = "fixture-metar-20261120T0000Z"
    base = datetime(2026, 11, 20, 0, 0, 0, tzinfo=UTC)
    received = to_iso(base + timedelta(minutes=2))
    rows: list[dict] = []
    payloads: dict[str, list[dict]] = {}
    for si, (icao, lon, lat) in enumerate(STATIONS):
        samples = []
        for h in range(0, 6):
            obs_t = base + timedelta(hours=h, minutes=10 * si)
            raw = {
                "icaoId": icao, "reportTime": to_iso(obs_t), "lat": lat, "lon": lon,
                "temp": round(10 + si + 2 * math.sin(h / 2), 1),
                "dewp": round(8 + si + 2 * math.cos(h / 2), 1),
                "wdir": "VRB" if si == 2 and h == 1 else (90 * si + 30 * h) % 360,
                "wspd": round(2 + si + h / 3, 1), "wgst": None,
                "visib": ">10" if si == 5 else "9999",
                "wxString": "-FG" if (si == 0 and h == 3) else None,
                "fltCat": "MVFR" if si % 2 else "VFR",
                "rawOb": f"{icao} {obs_t:%d%H%M}Z 27010KT 9999 FEW020 {10+si:02d}/{8+si:02d} Q1013",
            }
            samples.append(raw)
            rows.append({
                "station_id": icao, "source_id": "demo", "observed_at": to_iso(obs_t),
                "revision": "1", "received_at": received, "lon": lon, "lat": lat,
                "values": {
                    "temp_c": raw["temp"], "dewpoint_c": raw["dewp"],
                    "wind_speed_ms": round(raw["wspd"] * 0.514444, 3),
                    "wind_direction": {"degrees": None if raw["wdir"] == "VRB" else raw["wdir"],
                                       "variable": raw["wdir"] == "VRB", "raw": raw["wdir"]},
                    "visibility": {"meters": 10000.0 if raw["visib"] in ("9999", ">10") else None,
                                   "raw": raw["visib"], "qualifier": ">=" if raw["visib"] in ("9999", ">10") else "="},
                    "weather_phenomena": raw["wxString"], "raw_report": raw["rawOb"],
                }, "raw_ref": f"fixture-metar/{icao}-{h}.json",
            })
        payloads[icao] = samples
    rel = f"raw/metar/{snap_id}.json"
    _rel_write(rel, json.dumps(payloads, ensure_ascii=False, indent=1).encode())
    repo.ensure_dataset(METAR_DATASET, "demo", "fixture", "演示 METAR 站点观测", "EarthSim fixture", "")
    repo.insert_observations(rows)
    snapshot = {
        "snapshot_id": snap_id, "dataset_id": METAR_DATASET, "identity_key": "20261120T0000Z",
        "observed_start": to_iso(base), "observed_end": to_iso(base + timedelta(hours=5)),
        "payload_version": "1", "state": "published", "published_at": received,
        "details": {"kind": "fixture", "stations": [s[0] for s in STATIONS]},
    }
    repo.insert_snapshot(snapshot, [], publish=True)
    return {"snapshot_id": snap_id, "observations": len(rows)}


# --------------------------------------------------------------------------- DEM
def install_dem() -> dict:
    """Small DEM tile with metadata; rasterio/GDAL reads the .tif when present."""
    snap_id = "fixture-dem-alps"
    nx, ny = 64, 64
    lon0, lat0, dx, dy = 7.0, 45.0, 0.01, 0.01
    LON, LAT = np.meshgrid(lon0 + np.arange(nx) * dx, lat0 + np.arange(ny) * dy)
    elev = (800 + 2600 * np.exp(-((LON - 7.3) / 0.12) ** 2 - ((LAT - 45.8) / 0.1) ** 2)).astype("<f4")
    elev[10:14, 40:44] = -32767  # NoData sentinel
    meta = {
        "crs": "EPSG:4326", "vertical_datum": "EGM96 (MSL)", "nodata": -32767.0,
        "dx": dx, "dy": dy, "nx": nx, "ny": ny, "lon0": lon0, "lat0": lat0,
        "corner_lonlat": [[lon0, lat0], [lon0 + (nx - 1) * dx, lat0],
                          [lon0 + (nx - 1) * dx, lat0 + (ny - 1) * dy], [lon0, lat0 + (ny - 1) * dy]],
        "units": "m", "provider": "fixture", "product_version": "1",
        "note": "合成山谷地形，仅用于演示 DEM 加载与地形分辨率标记",
    }
    a = _rel_write(f"raw/topography/fixture/{snap_id}.bin", elev.tobytes(order="C"))
    m = _rel_write(f"raw/topography/fixture/{snap_id}.json",
                   json.dumps({**meta, "data_ref": a["relative_path"]}, ensure_ascii=False).encode())
    repo.ensure_dataset(DEM_DATASET, "demo", "fixture", "演示局部 DEM", "EarthSim fixture", "")
    gspec = gmod.GridSpec("EPSG:4326", nx, ny, lon0, lat0, dx, dy, False)
    fid = f"{snap_id}-elev"
    frame = {
        "frame_id": fid, "layer_id": "terrain", "level_type": "surface", "level_value": 0,
        "valid_time": to_iso(datetime.now(UTC)),
        "bbox": {"west": lon0, "south": lat0, "east": lon0 + (nx - 1) * dx, "north": lat0 + (ny - 1) * dy},
        "grid": gspec.to_dict(),
        "fields": [{"id": "elevation", "unit": "m"}],
        "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": snap_id,
                     "kind": "fixture", "source_id": "demo", "layer_id": "terrain",
                     "grid": gmod.describe_grid(gspec), "fields": [{"id": "elevation", "unit": "m"}],
                     "encoding": {"dtype": "float32", "missing": "-32767"}, **meta},
        "assets": [{"asset_id": fid + "-bin", "role": "grid", "relative_path": a["relative_path"],
                    "media_type": "application/octet-stream", "sha256": a["sha256"], "bytes": a["bytes"]}],
    }
    snapshot = {"snapshot_id": snap_id, "dataset_id": DEM_DATASET, "identity_key": snap_id,
                "payload_version": "1", "state": "published", "published_at": to_iso(datetime.now(UTC)),
                "details": meta}
    repo.insert_snapshot(snapshot, [frame], publish=True)
    return {"snapshot_id": snap_id, "assets": [a["relative_path"], m["relative_path"]], "frame": fid}


# --------------------------------------------------------------------------- orchestration
def install_all() -> dict:
    repo.ensure_migrated()
    return {
        "gfs": install_gfs(),
        "metar": install_metar(),
        "dem": install_dem(),
    }


def verify_all() -> dict:
    """Verify checksums of every registered asset."""
    bad: list[str] = []
    total = 0
    with repo.connect() as con:
        rows = list(con.execute("SELECT asset_id,relative_path,sha256,bytes FROM assets"))
    for r in rows:
        total += 1
        path = get_settings().data_root / r["relative_path"]
        if not path.exists():
            bad.append(f"{r['asset_id']}: missing")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != r["sha256"] or path.stat().st_size != r["bytes"]:
            bad.append(f"{r['asset_id']}: checksum/size mismatch")
    return {"checked": total, "ok": len(bad) == 0, "problems": bad}
