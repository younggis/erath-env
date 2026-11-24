"""Adapter unit tests. No live upstream calls are made here."""
from datetime import datetime, timezone

import numpy as np
import pytest

from earthsim.ingest import gfs, metar
from earthsim.ingest.base import IngestError


def test_gfs_cycle_urls_and_params():
    init = datetime(2026, 11, 20, 6, tzinfo=timezone.utc)
    assert "gfs.20261120/06" in gfs.cycle_url(init, 3)
    p = gfs.filter_params(init, 3)
    assert p["file"] == "gfs.t06z.pgrb2.0p25.f003"
    assert p["var_UGRD"] == "on"


def test_gfs_validate_and_decoder_injection(tmp_path):
    with pytest.raises(IngestError):
        gfs.validate_grib(b"<html>not grib</html>")
    path = tmp_path / "fake.grib"
    path.write_bytes(b"GRIB" + b"\x00" * 32)

    def fake_decoder(p):
        arr = np.zeros((721, 1441), dtype=np.float32)
        return {("wind10", "2026-11-20T03:00:00Z"): {"u": arr, "v": arr},
                ("temp2m", "2026-11-20T03:00:00Z"): {"2t": arr},
                ("rh2m", "2026-11-20T03:00:00Z"): {"2r": arr},
                ("mslp", "2026-11-20T03:00:00Z"): {"msl": arr},
                ("cloud_total", "2026-11-20T03:00:00Z"): {"tcc": arr},
                ("visibility_sfc", "2026-11-20T03:00:00Z"): {"vis": arr}}

    decoded = gfs.decode_messages(path, decoder=fake_decoder)
    frames = gfs.build_frames(datetime(2026, 11, 20, 0, tzinfo=timezone.utc), decoded, [3])
    assert len(frames) == 6
    decoded.pop(("rh2m", "2026-11-20T03:00:00Z"))
    with pytest.raises(IngestError) as e:
        gfs.build_frames(datetime(2026, 11, 20, 0, tzinfo=timezone.utc), decoded, [3])
    assert e.value.code == "INCOMPLETE_BATCH"


def test_metar_normalization_preserves_qualifiers():
    received = "2026-11-20T00:02:00Z"
    report = {"icaoId": "RJTT", "reportTime": "2026-11-20T00:00:00Z", "lat": 35.5, "lon": 139.7,
              "temp": 12, "dewp": 10, "wdir": "VRB", "wspd": 10, "visib": ">10", "wxString": "-FG"}
    o = metar.normalize(report, received)
    assert o["values"]["wind_speed_ms"] == pytest.approx(5.144)
    assert o["values"]["wind_direction"]["variable"] is True
    assert o["values"]["visibility"]["qualifier"] == ">"
    assert o["values"]["visibility"]["lower_bound"] is not None
    missing = metar.normalize({"icaoId": "X", "reportTime": "2026-11-20T00:00:00Z",
                               "temp": None, "visib": "", "wdir": "000"}, received)
    assert missing["values"]["temp_c"] is None
    assert missing["values"]["wind_direction"]["calm"] is True
    assert missing["values"]["visibility"]["meters"] is None
    plus = metar._visibility("6+")
    assert plus["qualifier"] == ">" and plus["lower_bound"] == pytest.approx(6 * 1609.344)



