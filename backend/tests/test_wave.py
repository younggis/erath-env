"""GFS-Wave adapter: decode contract, derived drift and catalog frames (no network)."""
from datetime import datetime, timezone

import numpy as np
import pytest

from earthsim.api.routes import LAYER_INFO
from earthsim.config import get_settings
from earthsim.fields import grid as gmod
from earthsim.fields.timeutil import to_iso
from earthsim.ingest import wave


def test_wave_filter_params_and_grid_contract():
    init = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
    p = wave.filter_params(init, 3)
    assert "/gfs.20261124/00/wave/gridded" == p["dir"]
    assert p["file"] == "gfswave.t00z.global.0p25.f003.grib2"
    assert p["var_HTSGW"] == "on" and p["var_DIRPW"] == "on"
    assert wave.WAVE_GRID.lon0 == -180.0 and wave.WAVE_GRID.lat0 == -90.0


def test_wave_frames_and_drift_direction(tmp_path):
    init = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
    valid = to_iso(init)
    height = np.full((721, 1441), 2.0, dtype=np.float32)
    period = np.full((721, 1441), 9.0, dtype=np.float32)
    # 90° oceanographic direction means waves come from the east.
    direction = np.full((721, 1441), 90.0, dtype=np.float32)

    def decoder(_):
        return {("wave_height", valid): {"swh": height},
                ("wave_period", valid): {"perpw": period},
                ("wave_direction", valid): {"dirpw": direction}}

    decoded = wave.decode_messages(tmp_path / "fake.grib2", decoder=decoder)
    frames = wave.build_frames(init, decoded, [0])
    assert len(frames) == 4
    by_layer = {f["layer_id"]: f for f in frames}
    assert by_layer["wave_height"]["fields"][0]["unit"] == "m"
    assert by_layer["wave_drift"]["fields"][0]["id"] == "u"
    asset_path = get_settings().data_root / by_layer["wave_drift"]["assets"][0]["relative_path"]
    arr = gmod.read_grid_binary(asset_path,
                                gmod.GridSpec.from_dict(by_layer["wave_drift"]["grid"]), 2)
    assert arr[10, 10, 0] == pytest.approx(-0.7, abs=1e-5)
    assert arr[10, 10, 1] == pytest.approx(0.0, abs=1e-5)


def test_wave_layers_registered_in_catalog():
    assert {"wave_height", "wave_period", "wave_direction", "wave_drift"} <= set(LAYER_INFO)
    assert LAYER_INFO["wave_drift"]["layer_type"] == "vector"
