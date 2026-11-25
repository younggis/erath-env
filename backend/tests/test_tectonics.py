"""Tectonic plate asset: validation, offline load and ETag revalidation."""
import json

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import tectonics
from earthsim.ingest.base import IngestError

SAMPLE = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"Name": "NA-EU", "PlateA": "NA", "PlateB": "EU", "Type": ""},
     "geometry": {"type": "LineString", "coordinates": [[-30, 40], [-20, 45], [-10, 50]]}},
]}


def test_validate_geojson_accepts_valid_lines():
    tectonics.validate_geojson(SAMPLE)


def test_validate_geojson_rejects_bad_coords_and_types():
    with pytest.raises(IngestError):
        tectonics.validate_geojson({"type": "Point", "coordinates": [0, 0]})
    bad = json.loads(json.dumps(SAMPLE))
    bad["features"][0]["geometry"]["coordinates"] = [[999, 0], [1, 1]]
    with pytest.raises(IngestError):
        tectonics.validate_geojson(bad)


def test_offline_bundled_asset_loads():
    data = tectonics.load_geojson()
    assert len(data["features"]) >= 200
    assert all(-180 <= c[0] <= 180 and -90 <= c[1] <= 90
               for f in data["features"] for c in f["geometry"]["coordinates"])


def test_static_endpoint_etag_and_304():
    client = TestClient(app)
    r = client.get("/api/v1/static/tectonic-plates")
    assert r.status_code == 200
    assert r.headers.get("etag", "").startswith('"')
    assert len(r.json()["features"]) >= 200

    r2 = client.get("/api/v1/static/tectonic-plates",
                    headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    assert r2.headers["etag"] == r.headers["etag"]


def test_refresh_with_injected_fetcher():
    payload = json.dumps(SAMPLE).encode()
    result = tectonics.refresh(fetcher=lambda url: payload)
    assert result["ok"] is True and result["features"] == 1
