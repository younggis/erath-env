"""TeleGeography cable cache: GeoJSON validation and ETag revalidation."""
import json

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import cables
from earthsim.ingest.base import IngestError

CABLE = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"id": "c1", "name": "SEA-ME-WE"},
     "geometry": {"type": "LineString", "coordinates": [[0, 0], [10, 5], [20, 3]]}},
]}
LANDING = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"id": "p1", "name": "Marseille"},
     "geometry": {"type": "Point", "coordinates": [5.3, 43.3]}},
]}


def test_validate_geojson_accepts_lines_and_points():
    cables.validate_geojson(CABLE, "cables")
    cables.validate_geojson(LANDING, "landing")


def test_validate_geojson_rejects_bad_payloads():
    with pytest.raises(IngestError):
        cables.validate_geojson({"type": "FeatureCollection", "features": []}, "empty")
    with pytest.raises(IngestError):
        cables.validate_geojson({"type": "Point", "coordinates": [0, 0]}, "wrong type")
    with pytest.raises(IngestError):
        cables.validate_geojson({"type": "FeatureCollection", "features": [
            {"geometry": {"type": "LineString", "coordinates": []}}]}, "no coords")


def test_refresh_and_etag_304():
    payloads = {cables.CABLE_URL: json.dumps(CABLE), cables.LANDING_URL: json.dumps(LANDING)}
    result = cables.refresh(etcher=lambda url: payloads[url])
    assert result["ok"] is True and result["features"] == 2

    asset = cables.read_asset("cables")
    assert asset is not None
    body, etag = asset
    assert etag.startswith('"') and etag.endswith('"')

    client = TestClient(app)
    r = client.get("/api/v1/infra/cables")
    assert r.status_code == 200 and r.headers["etag"] == etag
    assert len(r.json()["features"]) == 1

    r2 = client.get("/api/v1/infra/cables", headers={"If-None-Match": etag})
    assert r2.status_code == 304 and r2.headers["etag"] == etag

    r3 = client.get("/api/v1/infra/cables", params={"type": "landing"})
    assert r3.status_code == 200 and r3.json()["features"][0]["geometry"]["type"] == "Point"
