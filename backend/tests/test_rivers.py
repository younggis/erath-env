"""River GeoJSON: topology, attribute fields and ETag."""
import json

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import rivers
from earthsim.ingest.base import IngestError

SAMPLE = {"type": "FeatureCollection", "features": [{
    "type": "Feature",
    "geometry": {"type": "LineString", "coordinates": [[-74.0, 40.7], [-73.9, 40.8]]},
    "properties": {"scalerank": 2, "strokeweig": 0.5, "featurecla": "River", "name": "Test"},
}]}


def test_validate_accepts_valid_river():
    rivers.validate(SAMPLE)


def test_validate_rejects_bad_geometry_and_topology():
    bad = json.loads(json.dumps(SAMPLE))
    bad["features"][0]["geometry"]["type"] = "Point"
    with pytest.raises(IngestError):
        rivers.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["features"][0]["geometry"]["coordinates"] = [[-74.0, 40.7]]
    with pytest.raises(IngestError):
        rivers.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["features"][0]["geometry"]["coordinates"] = [[-200.0, 40.7], [-73.9, 40.8]]
    with pytest.raises(IngestError):
        rivers.validate(bad)


def test_validate_rejects_missing_or_bad_attributes():
    for field in rivers.REQUIRED_FIELDS:
        bad = json.loads(json.dumps(SAMPLE))
        del bad["features"][0]["properties"][field]
        with pytest.raises(IngestError):
            rivers.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["features"][0]["properties"]["scalerank"] = 99
    with pytest.raises(IngestError):
        rivers.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["features"][0]["properties"]["strokeweig"] = 0
    with pytest.raises(IngestError):
        rivers.validate(bad)


def test_bundled_asset_has_graded_global_network():
    data = rivers.load()
    feats = data["features"]
    assert len(feats) > 1000
    ranks = {f["properties"]["scalerank"] for f in feats}
    assert 1 in ranks and 6 in ranks  # both trunk and tributary classes
    assert all(f["geometry"]["type"] in ("LineString", "MultiLineString") for f in feats)
    assert all(len(f["geometry"]["coordinates"]) >= 2 for f in feats if
               f["geometry"]["type"] == "LineString")
    assert any(f["geometry"]["coordinates"][0][0] > 0 for f in feats)
    assert any(f["geometry"]["coordinates"][0][0] < 0 for f in feats)


def test_static_endpoint_etag_304():
    client = TestClient(app)
    r = client.get("/api/v1/static/rivers")
    assert r.status_code == 200
    assert r.headers.get("etag", "").startswith('"')
    assert r.json()["type"] == "FeatureCollection"
    r2 = client.get("/api/v1/static/rivers",
                    headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
