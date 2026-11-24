import math
from datetime import datetime, timezone

import numpy as np
import pytest

from earthsim.fields import grid as gm
from earthsim.fields.timeutil import (gfs_cycles, normalize_lon, parse_iso, to_iso,
                                      validate_forecast, valid_from_lead)
from earthsim.fields.wind import describe_wind, wind_direction_from, wind_speed
from earthsim.fields.units import dewpoint_from_temp_rh, kelvin_to_c, pa_to_hpa


def test_gfs_cycles_descending_and_aligned():
    now = datetime(2026, 11, 20, 13, 37, tzinfo=timezone.utc)
    cycles = gfs_cycles(now, 4)
    assert [c.hour for c in cycles] == [12, 6, 0, 18]
    assert all(c.minute == c.second == 0 for c in cycles)


def test_normalize_lon_and_time_roundtrip():
    assert normalize_lon(180) == -180
    assert normalize_lon(-181) == 179
    assert normalize_lon(540) == -180
    s = "2026-11-20T03:04:05Z"
    assert to_iso(parse_iso(s)) == s


def test_forecast_validation():
    init = datetime(2026, 11, 20, tzinfo=timezone.utc)
    valid = valid_from_lead(init, 3)
    assert validate_forecast(init, valid, 3) == 3
    with pytest.raises(ValueError):
        validate_forecast(init, init - __import__("datetime").timedelta(hours=1))


def test_grid_binary_roundtrip_and_sampling(tmp_path):
    g = gm.GridSpec("EPSG:4326", 4, 3, -180, -90, 120, 90)
    arr = np.arange(12, dtype=np.float32).reshape(3, 4, 1)
    p = tmp_path / "g.bin"
    gm.write_grid_binary(p, arr)
    back = gm.read_grid_binary(p, g, 1)
    np.testing.assert_allclose(back, arr)
    v, method = gm.bilinear_sample(g, back[:, :, 0], -60, 0)
    assert method == "bilinear"
    assert v[0] == pytest.approx(5.0)
    v180, _ = gm.bilinear_sample(g, back[:, :, 0], 180, 0)
    vm180, _ = gm.bilinear_sample(g, back[:, :, 0], -180, 0)
    assert v180[0] == pytest.approx(vm180[0])  # antimeridian wrap


def test_missing_handling(tmp_path):
    g = gm.GridSpec("EPSG:4326", 3, 3, 0, 0, 1, 1)
    arr = np.zeros((3, 3, 1), dtype=np.float32)
    arr[1, 1, 0] = np.nan
    v, method = gm.bilinear_sample(g, arr[:, :, 0], 1, 1, nearest_fallback=False)
    assert v[0] is None and method == "missing"


def test_wind_conventions():
    assert wind_speed(3, 4) == 5
    assert wind_direction_from(0, -5) == pytest.approx(0)    # from north
    assert wind_direction_from(-5, 0) == pytest.approx(90)   # from east (toward west)
    assert wind_direction_from(5, 0) == pytest.approx(270)   # from west (toward east)
    assert wind_direction_from(0, 0) is None
    d = describe_wind(0, -5)
    assert d["compass"] == "北" and d["to_north"] == pytest.approx(-1)


def test_units_and_derived_rh():
    assert kelvin_to_c(273.15) == pytest.approx(0)
    assert pa_to_hpa(101325) == pytest.approx(1013.25)
    assert 0 < dewpoint_from_temp_rh(20, 80) < 20
