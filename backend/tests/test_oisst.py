"""OISST adapter: ERDDAP query, grid normalization and frame contract (no network)."""
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from earthsim.api.routes import LAYER_INFO
from earthsim.config import get_settings
from earthsim.fields import grid as gmod
from earthsim.fields.timeutil import to_iso
from earthsim.ingest import oisst


def test_erddap_query_is_encoded_and_subsampled():
    url = oisst.request_url()
    assert "ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.nc?sst%5B%28last%29%5D" in url
    assert "%5B0%3A2%3A719%5D%5B0%3A2%3A1439%5D" in url
    assert oisst.OISST_GRID.nx == 721 and oisst.OISST_GRID.ny == 360


def test_decode_normalizes_lon_and_masks_land():
    raw = np.zeros((1, 1, 360, 720), dtype=np.float32)
    # ERDDAP lon 0..360: index 0 = 0.125E, index 360 = 180.125 -> -179.875.
    raw[0, 0, :, 0] = 20.0
    raw[0, 0, :, 360] = 10.0
    raw[0, 0, :, 719] = -999.0

    def reader(_: Path):
        return ({"time": np.array([1794052800.0])}, raw)

    observed, values = oisst.decode_nc(Path("fake.nc"), reader=reader)
    assert observed == to_iso(datetime(2026, 11, 7, 12, tzinfo=timezone.utc))
    assert values.shape == (360, 721)
    assert values[0, 0] == np.float32(10.0)   # -179.875 after roll
    assert values[0, 720] == np.float32(10.0)  # duplicated seam
    assert np.isnan(values[0, 359])  # old index 719 -> new index 359 after roll


def test_build_frames_and_registration():
    observed = "2026-11-07T12:00:00Z"
    values = np.full((360, 721), 18.0, dtype=np.float32)
    frames = oisst.build_frames(observed, values)
    assert len(frames) == 1 and frames[0]["layer_id"] == "sst"
    path = get_settings().data_root / frames[0]["assets"][0]["relative_path"]
    arr = gmod.read_grid_binary(path, gmod.GridSpec.from_dict(frames[0]["grid"]), 1)
    assert arr[0, 0, 0] == np.float32(18.0)
    assert "sst" in LAYER_INFO and LAYER_INFO["sst"]["unit"] == "degC"
