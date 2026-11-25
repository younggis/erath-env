"""GEFS ensemble adapter: ensemble mean/spread fields and probability contract."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from earthsim.api.routes import LAYER_INFO
from earthsim.config import get_settings
from earthsim.fields import grid as gmod
from earthsim.fields.timeutil import to_iso
from earthsim.ingest import gefs


def test_filter_params_and_grid():
    init = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
    p = gefs.filter_params(init, 6, "gespr")
    assert p["file"] == "gespr.t00z.pgrb2a.0p50.f006"
    assert "/gefs.20261124/00/atmos/pgrb2ap5" == p["dir"]
    assert gefs.GEFS_GRID.nx == 721 and gefs.GEFS_GRID.ny == 361


def test_decode_normalizes_native_grid():
    native = np.zeros((361, 720), dtype=np.float32)
    native[:, 0] = 10.0
    native[:, 360] = 20.0

    def decoder(_: Path):
        return {"10u": native}

    decoded = gefs.decode_messages(Path("fake.grib2"), decoder=decoder)
    assert decoded["10u"].shape == (361, 721)
    assert decoded["10u"][0, 0] == np.float32(20.0)
    assert decoded["10u"][0, 720] == np.float32(20.0)


def test_build_frames_uses_each_lead_own_fields():
    init = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
    shape = (gefs.GEFS_GRID.ny, gefs.GEFS_GRID.nx)

    def fields(speed: float) -> dict:
        return {"10u": np.full(shape, speed, np.float32),
                "10v": np.zeros(shape, np.float32),
                "2t": np.full(shape, 290.0, np.float32)}

    by_valid = {}
    for lead in (0, 3, 6):
        valid = to_iso(init + timedelta(hours=lead))
        by_valid[("geavg", valid)] = fields(2.0 + lead)
        by_valid[("gespr", valid)] = fields(1.0)
    frames = gefs.build_frames(init, {}, {}, [0, 3, 6], by_valid=by_valid)
    assert len(frames) == 15
    wind = [f for f in frames if f["layer_id"] == "gefs_wind10_mean"]
    assert len({f["frame_id"] for f in wind}) == 3
    values = []
    for f in wind:
        path = get_settings().data_root / f["assets"][0]["relative_path"]
        arr = gmod.read_grid_binary(path, gmod.GridSpec.from_dict(f["grid"]), 2)
        values.append(float(arr[0, 0, 0]))
    assert values == [2.0, 5.0, 8.0]  # each lead retains its own magnitude


def test_build_frames_and_probability():
    init = datetime(2026, 11, 24, 0, tzinfo=timezone.utc)
    shape = (361, 721)
    mean = {"10u": np.full(shape, 12.0, np.float32),
            "10v": np.full(shape, 0.0, np.float32),
            "2t": np.full(shape, 290.0, np.float32)}
    spread = {"10u": np.full(shape, 2.0, np.float32),
              "10v": np.full(shape, 0.0, np.float32),
              "2t": np.full(shape, 1.5, np.float32)}
    frames = gefs.build_frames(init, mean, spread, [0])
    assert len(frames) == 5
    by_layer = {f["layer_id"]: f for f in frames}
    prob_path = get_settings().data_root / by_layer["gefs_wind_prob"]["assets"][0]["relative_path"]
    prob = gmod.read_grid_binary(prob_path, gmod.GridSpec.from_dict(by_layer["gefs_wind_prob"]["grid"]), 1)
    assert prob[0, 0, 0] > 80  # 12 m/s with 2 m/s spread -> high exceedance probability
    assert "gefs_wind_prob" in LAYER_INFO
