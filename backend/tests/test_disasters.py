"""Global disaster adapters: pure parsing, dedup and API exposure (no network)."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.catalog import repository as repo
from earthsim.fields.timeutil import to_iso
from earthsim.ingest import disasters

client = TestClient(app)


def test_gdacs_rows_and_timeline_points():
    received = to_iso(datetime(2026, 11, 24, 12, tzinfo=timezone.utc))
    data = {"features": [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [80.2, 15.8]},
        "properties": {
            "eventtype": "TC", "eventid": 1001346, "episodeid": 10,
            "name": "Tropical Cyclone MURASU-26", "alertlevel": "Red", "alertscore": 3,
            "country": "India", "source": "JTWC", "iscurrent": "true",
            "datemodified": "2026-11-24T06:00:00", "fromdate": "2026-11-01T00:00:00",
            "todate": "2026-11-24T06:00:00",
            "severitydata": {"severitytext": "Hurricane"},
            "url": {"report": "https://example.test/report"},
        },
    }]}
    rows = disasters.gdacs_rows(data, received)
    assert len(rows) == 1
    assert rows[0]["station_id"] == "gdacs-1001346-10"
    assert rows[0]["values"]["event_type"] == "TC"
    assert rows[0]["observed_at"] == "2026-11-24T06:00:00Z"

    points = disasters.timeline_points([
        {"longitude": "80.2", "latitude": "15.8", "advisory_datetime": "01 Nov 2026 06:00",
         "wind_speed": "25.72", "storm_status": ["Tropical Storm"], "actual": "True"},
        {"longitude": "81.8", "latitude": "16.4", "advisory_datetime": "01 Nov 2026 12:00",
         "wind_speed": "30.86", "storm_status": ["Tropical Storm"], "actual": "False"},
    ], received)
    got = [(p["lon"], p["lat"]) for p in points]
    assert len(got) == 2
    assert got[0][0] == pytest.approx(80.2) and got[0][1] == pytest.approx(15.8)
    assert got[1][0] == pytest.approx(81.8) and got[1][1] == pytest.approx(16.4)
    assert points[0]["forecast"] is False and points[1]["forecast"] is True
    assert points[0]["time"] == "2026-11-01T06:00:00Z"


def test_eonet_suppresses_duplicate_nearby_wildfire():
    received = to_iso(datetime(2026, 11, 24, 12, tzinfo=timezone.utc))
    repo.insert_observations([{
        "station_id": "gdacs-1033959-9", "source_id": "gdacs",
        "observed_at": received, "received_at": received,
        "lon": -79.8, "lat": 38.3, "values": {"event_type": "WF"},
    }])
    data = {"features": [
        {"geometry": {"type": "Point", "coordinates": [-79.791, 38.313]},
         "properties": {"id": "EONET_1", "title": "Wildfire Virginia",
                        "date": "2026-11-24T06:00:00Z", "magnitudeValue": 900,
                        "magnitudeUnit": "acres",
                        "categories": [{"id": "wildfires"}],
                        "sources": [{"id": "IRWIN"}]}},
        {"geometry": {"type": "Point", "coordinates": [139.7, 35.5]},
         "properties": {"id": "EONET_2", "title": "Wildfire Japan",
                        "date": "2026-11-24T06:00:00Z",
                        "categories": [{"id": "wildfires"}], "sources": []}},
    ]}
    primary = repo.query_stations(None, received, max_age_minutes=7 * 24 * 60, source_id="gdacs")
    rows = disasters.eonet_rows(data, received, primary)
    assert [r["station_id"] for r in rows] == ["eonet-EONET_2"]
    assert rows[0]["values"]["event_type"] == "WF"


def test_firms_csv_parsing_and_ranking():
    received = to_iso(datetime(2026, 11, 24, 12, tzinfo=timezone.utc))
    csv_text = (
        "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,confidence,frp,daynight\n"
        "38.3,-79.8,330.1,0.4,0.4,2026-11-24,1130,N20,h,12.5,D\n"
        "-3.1,120.2,310.5,0.4,0.4,2026-11-24,1135,N20,l,2.1,D\n"
    )
    rows = disasters.firms_rows(csv_text, received)
    assert len(rows) == 2
    assert rows[0]["values"]["frp_mw"] == 12.5
    assert rows[0]["observed_at"] == "2026-11-24T11:30:00Z"
    assert rows[1]["lat"] == -3.1


def test_disaster_events_exposed_by_realtime_api():
    received = to_iso(datetime(2026, 11, 24, 12, tzinfo=timezone.utc))
    repo.insert_observations([{
        "station_id": "gdacs-api-check", "source_id": "gdacs",
        "observed_at": received, "received_at": received,
        "lon": 10.0, "lat": 20.0, "values": {"event_type": "FL", "alert_level": "Orange"},
    }])
    r = client.get("/api/v1/realtime/events", params={"type": "gdacs"})
    assert r.status_code == 200
    assert any(e["station_id"] == "gdacs-api-check" for e in r.json()["events"])
    tracks = client.get("/api/v1/realtime/tracks")
    assert tracks.status_code == 200 and isinstance(tracks.json().get("tracks"), list)
