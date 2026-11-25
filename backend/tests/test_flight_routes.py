"""Flight route asset: dedup validation, coordinate filtering and ETag."""
import json

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import flight_routes
from earthsim.ingest.base import IngestError

SAMPLE = {"airports": {
    "A": {"lat": 10.0, "lon": 20.0, "name": "A"},
    "B": {"lat": -30.0, "lon": -50.0, "name": "B"},
}, "routes": [["A", "B"]]}


def test_validate_accepts_valid_routes():
    flight_routes.validate(SAMPLE)


def test_validate_rejects_duplicate_and_unknown_airports():
    dup = json.loads(json.dumps(SAMPLE))
    dup["routes"].append(["B", "A"])
    with pytest.raises(IngestError):
        flight_routes.validate(dup)
    unknown = json.loads(json.dumps(SAMPLE))
    unknown["routes"] = [["A", "ZZZ"]]
    with pytest.raises(IngestError):
        flight_routes.validate(unknown)


def test_validate_rejects_out_of_range_coords():
    bad = json.loads(json.dumps(SAMPLE))
    bad["airports"]["A"]["lat"] = 95
    with pytest.raises(IngestError):
        flight_routes.validate(bad)


def test_bundled_asset_loads_deduplicated_routes():
    data = flight_routes.load()
    assert len(data["routes"]) >= 3000
    keys = [tuple(sorted(p)) for p in data["routes"]]
    assert len(keys) == len(set(keys))  # deduplicated
    assert all(p[0] in data["airports"] and p[1] in data["airports"] for p in data["routes"])


def test_static_endpoint_etag_304():
    client = TestClient(app)
    r = client.get("/api/v1/static/flight-routes")
    assert r.status_code == 200
    assert r.headers.get("etag", "").startswith('"')
    assert len(r.json()["routes"]) >= 3000
    r2 = client.get("/api/v1/static/flight-routes",
                    headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
