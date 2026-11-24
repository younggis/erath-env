"""NASA FIRMS adapter: CSV parse, FRP threshold, no-key degradation, API."""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.catalog import repository as repo
from earthsim.config import get_settings
from earthsim.fields.timeutil import to_iso
from earthsim.ingest import firms

CSV = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,frp,daynight\n"
    "38.3,-79.8,330.1,0.4,0.4,2026-11-25,1130,N20,h,12.5,D\n"
    "-3.1,120.2,310.5,0.4,0.4,2026-11-25,1135,N20,l,2.1,D\n"
    "-12.5,-60.1,360.0,0.4,0.4,2026-11-25,1140,N20,h,45.0,D\n"
)
RECEIVED = "2026-11-25T12:00:00Z"


def test_status_without_key():
    get_settings().firms_map_key = ""
    s = firms.status()
    assert s["enabled"] is False and s["configured"] is False
    assert "未启用" in s["note"]


def test_refresh_degrades_without_key():
    get_settings().firms_map_key = ""
    result = firms.refresh()
    assert result["ok"] is False
    assert result["enabled"] is False
    assert result["error"] == "MISSING_API_KEY"


def test_parse_fires_applies_frp_threshold():
    rows = firms.parse_fires(CSV, RECEIVED, min_frp=10.0)
    assert len(rows) == 2
    frps = sorted(r["values"]["frp_mw"] for r in rows)
    assert frps == [12.5, 45.0]
    for r in rows:
        assert -180 <= r["lon"] <= 180 and -90 <= r["lat"] <= 90
        assert r["source_id"] == "nasa_firms"
        assert r["values"]["confidence"] in {"h", "n", "l"}


def test_parse_fires_zero_threshold_keeps_all():
    assert len(firms.parse_fires(CSV, RECEIVED, min_frp=0.0)) == 3


def test_fires_endpoint_returns_valid_coords():
    get_settings().firms_map_key = "TEST_KEY"
    repo.insert_observations(firms.parse_fires(CSV, RECEIVED, min_frp=10.0))
    client = TestClient(app)
    r = client.get("/api/v1/realtime/fires")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is True and data["count"] >= 2
    for fire in data["fires"]:
        assert -180 <= fire["lon"] <= 180
        assert -90 <= fire["lat"] <= 90
        assert "frp_mw" in fire["values"]
