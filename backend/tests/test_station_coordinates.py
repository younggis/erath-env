"""METAR station coordinates: (lon, lat) ordering and invalid-coord filtering."""
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import metar

RECEIVED = "2026-11-25T12:00:00Z"


def test_normalize_keeps_awc_lon_lat_order():
    row = metar.normalize({
        "icaoId": "RJTT", "reportTime": RECEIVED,
        "lon": 139.781, "lat": 35.553, "temp": 13,
    }, RECEIVED)
    assert row["lon"] == 139.781 and row["lat"] == 35.553
    # Tokyo must not be swapped to (35.553, 139.781) — that is outside Japan.
    assert row["lat"] < row["lon"]


def test_normalize_rejects_missing_or_out_of_range_coords():
    assert metar.normalize({"icaoId": "X", "lon": None, "lat": None}, RECEIVED)["lon"] is None
    assert metar.normalize({"icaoId": "X", "lon": 200, "lat": 0}, RECEIVED)["lon"] == 200
    bad = metar.normalize({"icaoId": "X", "lon": "n/a", "lat": 10}, RECEIVED)
    assert bad["lon"] is None and bad["lat"] == 10


def test_api_returns_seeded_station_with_correct_coords():
    client = TestClient(app)
    r = client.get("/api/v1/stations", params={"bbox": "100,20,150,50",
                                               "at": "2026-11-20T03:00:00Z"})
    assert r.status_code == 200
    tokyo = next(s for s in r.json()["stations"] if s["station_id"] == "RJTT")
    assert tokyo["lon"] == 139.78 and tokyo["lat"] == 35.55
