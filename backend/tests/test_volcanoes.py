"""Volcano static asset: field validation, offline load and ETag revalidation."""
import json

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import volcanoes
from earthsim.ingest.base import IngestError

SAMPLE = {"features": [
    {"id": "x", "name": "Test", "country": "JP", "region": "Honshu",
     "lat": 35.0, "lon": 139.0, "elev": 500.0,
     "type": "Stratovolcano", "status": "Historical",
     "last_code": "D1", "last_year": 1600},
]}


def test_validate_accepts_valid_row():
    volcanoes.validate(SAMPLE)


def test_validate_rejects_bad_coords_and_elevation():
    for mutate in (
        lambda r: r.update(lon=999),
        lambda r: r.update(lat=-95),
        lambda r: r.update(elev="high"),
    ):
        bad = json.loads(json.dumps(SAMPLE))
        mutate(bad["features"][0])
        with pytest.raises(IngestError):
            volcanoes.validate(bad)


def test_bundled_asset_loads_with_fields():
    data = volcanoes.load()
    assert len(data["features"]) >= 1500
    assert all({"lat", "lon", "elev", "name", "last_year"} <= set(row)
               for row in data["features"])


def test_static_endpoint_etag_304():
    client = TestClient(app)
    r = client.get("/api/v1/static/volcanoes")
    assert r.status_code == 200
    assert r.headers.get("etag", "").startswith('"')
    assert len(r.json()["features"]) >= 1500

    r2 = client.get("/api/v1/static/volcanoes",
                    headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    assert r2.headers["etag"] == r.headers["etag"]
