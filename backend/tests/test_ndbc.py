"""NDBC buoy adapter: MM missing markers, UTC timestamps and buoy API."""
from datetime import datetime

from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.catalog import repository as repo
from earthsim.ingest import ndbc

SAMPLE = """#STN       LAT      LON  YYYY MM DD hh mm WDIR WSPD   GST WVHT  DPD APD MWD   PRES  PTDY  ATMP  WTMP  DEWP  VIS   TIDE
#text      deg      deg   yr mo day hr mn degT  m/s   m/s   m   sec sec degT   hPa   hPa  degC  degC  degC  nmi     ft
22101    37.24   126.02  2026 11 24 16 00 340   6.0    MM  0.5   0   MM  MM     MM    MM   3.9  14.3    MM   MM     MM
41004    32.502  -79.099 2026 11 24 16 00  20  14.0  17.0   MM  MM   MM  MM 1020.7  +1.5  19.4  24.7  17.0   MM     MM
"""


def test_parse_missing_handlers():
    assert ndbc.parse_missing("MM") is None
    assert ndbc.parse_missing("") is None
    assert ndbc.parse_missing("N/A") is None
    assert ndbc.parse_missing("9999") is None
    assert ndbc.parse_missing("abc") is None
    assert ndbc.parse_missing("3.5") == 3.5
    assert ndbc.parse_missing("+1.5") == 1.5


def test_normalize_mm_to_none_and_utc_iso():
    line = SAMPLE.splitlines()[2]
    row = ndbc.normalize(line, "2026-11-24T16:30:00Z")
    assert row is not None
    assert row["station_id"] == "22101"
    assert row["lat"] == 37.24 and row["lon"] == 126.02
    assert row["observed_at"] == "2026-11-24T16:00:00Z"
    assert row["values"]["wind_speed_ms"] == 6.0
    assert row["values"]["wave_height_m"] == 0.5
    assert row["values"]["gust_ms"] is None
    assert row["values"]["pressure_hpa"] is None
    assert row["values"]["water_temp_c"] == 14.3


def test_parse_text_skips_headers_and_dedups():
    rows = ndbc.parse_text(SAMPLE + SAMPLE.splitlines()[2] + "\n")
    assert len(rows) == 2
    assert {r["station_id"] for r in rows} == {"22101", "41004"}
    assert all(r["source_id"] == "noaa_ndbc" for r in rows)


def test_buoys_endpoint_returns_iso_timestamps():
    repo.insert_observations(ndbc.parse_text(SAMPLE))
    client = TestClient(app)
    r = client.get("/api/v1/obs/buoys", params={"max_age_minutes": 100000})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 2
    assert data["source_id"] == "noaa_ndbc"
    for buoy in data["buoys"]:
        assert buoy["observed_at"].endswith("Z")
        datetime.fromisoformat(buoy["observed_at"].replace("Z", "+00:00"))
        assert isinstance(buoy["values"], dict)
