"""Regression tests: data correctness and DEM registration."""
from datetime import datetime, timezone

from earthsim.catalog import repository as repo
from earthsim.ingest import gfs
from earthsim.config import get_settings


def test_cloud_mapping_is_not_surface_temperature():
    # surface 't' is paramId 130 air_temperature (K), never total cloud cover.
    assert "t" not in gfs.FIELD_MAP["cloud_total"][0]
    assert gfs.FIELD_MAP["cloud_total"][1] == "atmosphere"
    assert gfs.FIELD_MAP["visibility_sfc"][1] == "surface"
    assert "var_TCDC" not in gfs.filter_params(datetime(2026, 11, 20, tzinfo=timezone.utc), 0)


def test_dem_terrain_frame_registered():
    snap = repo.get_active_snapshot("demo-dem")
    assert snap is not None
    frames = repo.list_frames("terrain", snap["snapshot_id"])
    assert len(frames) == 1
    f = repo.get_frame(frames[0]["frame_id"])
    assert f["fields"][0]["id"] == "elevation"
    assert f["grid"]["nx"] == 64
