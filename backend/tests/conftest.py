"""Test isolation: every test run gets its own temporary catalog and data root.

The seed below exists only for pytest.  It publishes a handful of small,
real-kind snapshots through the same repository API the live collectors use;
there is no demo/fixture mode in the application itself.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from earthsim.config import Settings, get_settings, set_settings
from earthsim.catalog import repository as repo
from earthsim.fields import grid as gmod
from earthsim.fields.timeutil import to_iso

UTC = timezone.utc
INIT = datetime(2026, 11, 20, tzinfo=UTC)
GFS_SNAPSHOT = "test-gfs-20261120T0000Z"
DEM_SNAPSHOT = "test-dem-alps"
LAYERS = {
    "wind10": 2, "temp2m": 1, "rh2m": 1, "mslp": 1,
    "cloud_total": 1, "visibility_sfc": 1,
}


def _write(rel: str, data: bytes) -> dict:
    root = get_settings().data_root
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"relative_path": rel, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data), "media_type": "application/octet-stream"}


def _seed() -> None:
    grid = gmod.GridSpec("EPSG:4326", nx=9, ny=5, lon0=-180.0, lat0=-90.0,
                         dx=45.0, dy=45.0, wrap_longitude=True)
    lons, lats = np.meshgrid(grid.lons(), grid.lats())

    repo.ensure_dataset("noaa-gfs", "noaa_gfs", "forecast",
                        "Test forecast fields", "EarthSim tests", "")
    frames = []
    for lead in range(25):
        valid = to_iso(INIT + timedelta(hours=lead))
        for layer, ncomp in LAYERS.items():
            arr = np.empty((grid.ny, grid.nx, ncomp), dtype="<f4")
            for c in range(ncomp):
                arr[:, :, c] = 10 + c + 2 * np.cos(np.deg2rad(lons)) + np.sin(np.deg2rad(lats))
            fid = f"test-{layer}-t{lead:02d}"
            asset = _write(f"derived/{GFS_SNAPSHOT}/{fid}.bin", arr.tobytes(order="C"))
            frames.append({
                "frame_id": fid, "layer_id": layer,
                "level_type": "height_agl", "level_value": 10 if layer == "wind10" else 2,
                "valid_time": valid, "bbox": {"west": -180, "south": -90, "east": 180, "north": 90},
                "grid": grid.to_dict(),
                "fields": ([{"id": "u", "unit": "m/s"}, {"id": "v", "unit": "m/s"}]
                           if ncomp == 2 else [{"id": layer, "unit": "1"}]),
                "manifest": {"schema_version": 1, "frame_id": fid, "snapshot_id": GFS_SNAPSHOT,
                             "kind": "forecast", "source_id": "noaa_gfs", "layer_id": layer,
                             "init_time": to_iso(INIT), "valid_time": valid,
                             "received_at": to_iso(INIT), "grid": gmod.describe_grid(grid),
                             "encoding": {"dtype": "float32", "byte_order": "little", "missing": "nan"}},
                "assets": [{"asset_id": fid + "-bin", "role": "grid", **asset}],
            })
    repo.insert_snapshot({"snapshot_id": GFS_SNAPSHOT, "dataset_id": "noaa-gfs",
                          "identity_key": to_iso(INIT), "init_time": to_iso(INIT),
                          "payload_version": "1", "published_at": to_iso(INIT)}, frames, publish=True)
    repo.upsert_source("noaa_gfs", success=True, at=to_iso(INIT))

    obs_at = to_iso(INIT + timedelta(hours=3))
    repo.insert_observations([{
        "station_id": "RJTT", "source_id": "awc_metar", "observed_at": obs_at,
        "received_at": obs_at, "lon": 139.78, "lat": 35.55,
        "values": {"temp": 293.15, "dewpoint": 288.15},
    }])
    repo.upsert_source("awc_metar", success=True, at=obs_at)

    dem_grid = gmod.GridSpec("EPSG:4326", 64, 64, 7.0, 45.0, 0.01, 0.01)
    dem = np.arange(64 * 64, dtype="<f4").reshape(64, 64, 1)
    fid = "test-dem-alps-elev"
    asset = _write(f"derived/{DEM_SNAPSHOT}/{fid}.bin", dem.tobytes(order="C"))
    repo.ensure_dataset("cop-dem", "cop_dem", "forecast", "Test terrain", "EarthSim tests", "")
    repo.insert_snapshot({"snapshot_id": DEM_SNAPSHOT, "dataset_id": "cop-dem",
                          "identity_key": to_iso(INIT), "init_time": to_iso(INIT),
                          "payload_version": "1", "published_at": to_iso(INIT)}, [{
        "frame_id": fid, "layer_id": "terrain", "level_type": "surface", "level_value": 0,
        "valid_time": to_iso(INIT), "grid": dem_grid.to_dict(),
        "fields": [{"id": "elevation", "unit": "m"}],
        "manifest": {"kind": "forecast", "source_id": "cop_dem", "layer_id": "terrain",
                     "grid": gmod.describe_grid(dem_grid)},
        "assets": [{"asset_id": fid + "-bin", "role": "grid", **asset}],
    }], publish=True)


@pytest.fixture(scope="session", autouse=True)
def isolated_data(tmp_path_factory):
    root = tmp_path_factory.mktemp("earthsim-data")
    s = get_settings()
    s.data_root = root
    for sub in ("catalog", "raw", "derived", "tmp"):
        (root / sub).mkdir(exist_ok=True)
    repo.ensure_migrated()
    _seed()
    yield s


@pytest.fixture(autouse=True)
def reset_settings(isolated_data):
    set_settings(isolated_data)
    yield
