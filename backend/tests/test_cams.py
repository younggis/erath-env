"""CAMS/Open-Meteo adapter: grid sampling, row-major decode and frame contract."""
from datetime import datetime, timezone

import numpy as np

from earthsim.api.routes import LAYER_INFO
from earthsim.config import get_settings
from earthsim.fields import grid as gmod
from earthsim.fields.timeutil import to_iso
from earthsim.ingest import cams


def test_sample_coordinates_and_grid():
    coords = cams.sample_coordinates()
    assert len(coords) == (cams.CAMS_GRID.nx - 1) * cams.CAMS_GRID.ny
    assert coords[0] == (-87.5, -180.0)
    assert coords[-1] == (87.5, 175.0)
    assert cams.CAMS_GRID.nx == 73 and cams.CAMS_GRID.ny == 36


def test_fetch_grid_row_major_decode(monkeypatch):
    def fake_get(params):
        n = len(params["latitude"].split(","))
        out = []
        for i in range(n):
            current = {"time": 1794052800}
            if i == 0:
                current.update({"aerosol_optical_depth": 0.4, "dust": 12.0, "pm2_5": 8.0})
            out.append({"current": current})
        return out

    monkeypatch.setattr(cams, "_get_json", fake_get)
    observed, values = cams.fetch_grid()
    assert observed == to_iso(datetime(2026, 11, 7, 12, tzinfo=timezone.utc))
    assert values["aerosol_optical_depth"].shape == (36, 73)
    assert values["aerosol_optical_depth"][0, 0] == np.float32(0.4)
    assert values["aerosol_optical_depth"][0, 72] == np.float32(0.4)  # seam
    assert np.isnan(values["aerosol_optical_depth"][0, 1])


def test_build_frames_and_registration():
    observed = "2026-11-07T12:00:00Z"
    values = {v: np.full((36, 73), 1.0, dtype=np.float32) for v in cams.VARIABLES}
    frames = cams.build_frames(observed, values)
    assert len(frames) == 3
    assert {f["layer_id"] for f in frames} == {"cams_aod", "cams_dust", "cams_pm25"}
    path = get_settings().data_root / frames[0]["assets"][0]["relative_path"]
    arr = gmod.read_grid_binary(path, gmod.GridSpec.from_dict(frames[0]["grid"]), 1)
    assert arr[0, 0, 0] == np.float32(1.0)
    assert LAYER_INFO["cams_aod"]["palette"] == "aod"
