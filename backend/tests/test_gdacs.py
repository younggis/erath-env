"""GDACS adapter: GeoJSON impact polygons, hazard classes and refresh."""
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import disasters, gdacs


def test_classify_event():
    assert gdacs.classify_event("EQ") == "地震"
    assert gdacs.classify_event("TC") == "热带气旋"
    assert gdacs.classify_event("FL") == "洪水"
    assert gdacs.classify_event("XYZ") == "XYZ"


def test_parse_ring_validates_and_closes():
    assert gdacs.parse_ring([[0, 0], [1, 0], [1, 1]]) == [
        [0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 0.0]]
    assert gdacs.parse_ring([[999, 0], [1, 0], [1, 1]]) is None
    assert gdacs.parse_ring([[0, 0]]) is None


def _geometry(event_id=1, gtype="Polygon"):
    if gtype == "Polygon":
        geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    else:
        geometry = {"type": "MultiPolygon", "coordinates": [
            [[[0, 0], [1, 0], [1, 1], [0, 0]]],
            [[[2, 2], [3, 2], [3, 3], [2, 2]]],
        ]}
    return {"type": "FeatureCollection", "features": [{
        "type": "Feature", "geometry": geometry,
        "properties": {"eventid": event_id, "eventtype": "FL", "name": "Flood",
                       "alertlevel": "Red", "htmldescription": "Severe flood",
                       "url": {"report": "https://example.com"}},
    }]}


def test_parse_geojson_polygons_and_multi_hazards():
    one = gdacs.parse_geojson(_geometry(1), "2026-11-25T00:00:00Z")
    assert len(one) == 1 and len(one[0]["rings"]) == 1
    assert one[0]["event_class"] == "洪水" and one[0]["alert_color"] == "#ff4d5e"

    multi = gdacs.parse_geojson(_geometry(2, "MultiPolygon"), "t")
    assert len(multi[0]["rings"]) == 2
    point_only = gdacs.parse_geojson({"features": [{
        "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": {}}]}, "t")
    assert point_only == []


def _feature(event_id, etype, alert):
    return {
        "type": "Feature", "geometry": {"type": "Point", "coordinates": [10, 20]},
        "properties": {
            "eventtype": etype, "eventid": event_id, "episodeid": 1,
            "name": f"Event {event_id}", "alertlevel": alert,
            "fromdate": "2026-11-25T00:00:00", "todate": "2026-11-26T00:00:00",
            "url": {"geometry": f"geom://{event_id}", "report": "https://example.com"},
        },
    }


def test_refresh_and_polygons_endpoint():
    main = {"type": "FeatureCollection", "features": [
        _feature(1, "EQ", "Red"), _feature(2, "FL", "Orange"), _feature(3, "TC", "Green"),
    ]}

    def fake_fetch(url):
        if url == disasters.GDACS_URL:
            return main
        if url == "geom://1":
            return _geometry(1)
        return {"features": []}

    result = gdacs.refresh(fetcher=fake_fetch)
    assert result["ok"] is True
    assert result["events"] == 3 and result["polygons"] == 1

    client = TestClient(app)
    r = client.get("/api/v1/realtime/gdacs/polygons")
    assert r.status_code == 200
    data = r.json()
    assert len(data["polygons"]) >= 1
    assert all(-180 <= lon <= 180 and -90 <= lat <= 90
               for poly in data["polygons"] for ring in poly["rings"] for lon, lat in ring)
