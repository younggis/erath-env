"""OpenAQ v3 adapter: pagination, unit conversion, AQI and no-key degradation."""
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.catalog import repository as repo
from earthsim.config import get_settings
from earthsim.ingest import openaq

LOCATION = {
    "id": 123, "name": "Station A", "latitude": 35.6, "longitude": 139.7,
    "sensors": [
        {"parameter": {"name": "pm25", "units": "µg/m³"},
         "last_value": 12.5, "last_datetime": "2026-11-25T00:00:00Z"},
        {"parameter": {"name": "no2", "units": "ppb"},
         "last_value": 20, "last_datetime": "2026-11-25T00:00:00Z"},
    ],
}


def test_normalize_units():
    assert openaq.normalize_unit(12.5, "µg/m³", "pm25") == 12.5
    assert openaq.normalize_unit(5, "ug/m3", "pm25") == 5.0
    no2 = openaq.normalize_unit(20, "ppb", "no2")
    assert no2 is not None and abs(no2 - 20 * 46.01 / 24.45) < 0.01
    ppm = openaq.normalize_unit(1, "ppm", "o3")
    assert ppm is not None and abs(ppm - 1000 * 48.0 / 24.45) < 0.1
    assert openaq.normalize_unit("bad", "ppb", "no2") is None


def test_pm25_aqi_breakpoints():
    assert openaq.pm25_aqi(0) == 0
    assert openaq.pm25_aqi(35.4) == 100
    assert openaq.pm25_aqi(500) == 500
    assert openaq.pm25_aqi(None) is None


def test_parse_location_normalizes_and_checks_coords():
    row = openaq.parse_location(LOCATION, "2026-11-25T01:00:00Z")
    assert row is not None
    assert row["station_id"] == "openaq-123"
    assert row["lon"] == 139.7 and row["lat"] == 35.6
    assert row["values"]["pm25_ugm3"] == 12.5
    assert row["values"]["aqi_pm25"] is not None
    assert row["values"]["sensor_time"].endswith("Z")
    assert openaq.parse_location({"latitude": 999, "longitude": 0}, "t") is None


def test_fetch_all_pages(monkeypatch):
    get_settings().openaq_api_key = "TEST_KEY"
    get_settings().openaq_page_size = 2
    get_settings().openaq_max_pages = 3
    calls = []

    def fake_fetch(url, params, timeout):
        page = params["page"]
        calls.append(page)
        results = [LOCATION] if page == 2 else [LOCATION, LOCATION]
        return {"results": results, "meta": {"found": 3}}

    rows = openaq.fetch_all(fetcher=fake_fetch)
    assert calls == [1, 2]
    assert len(rows) == 3


def test_refresh_degrades_without_key():
    get_settings().openaq_api_key = ""
    result = openaq.refresh()
    assert result["ok"] is False and result["enabled"] is False
    assert result["error"] == "MISSING_API_KEY"


def test_air_quality_endpoint_valid_values_and_coords():
    get_settings().openaq_api_key = "TEST_KEY"
    row = openaq.parse_location(LOCATION, "2026-11-25T01:00:00Z")
    repo.insert_observations([row])
    client = TestClient(app)
    r = client.get("/api/v1/obs/air-quality")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 1
    for station in data["stations"]:
        assert -180 <= station["lon"] <= 180
        assert -90 <= station["lat"] <= 90
        assert "pm25_ugm3" in station["values"]
