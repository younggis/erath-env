"""Power plant asset: cleaning invariants, fuel enum and ETag."""
import json

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import power_plants
from earthsim.ingest.base import IngestError

SAMPLE = {"fuels": list(power_plants.FUELS),
          "plants": [[40.0, -74.0, 1200.0, 3, "Test Nuclear"]]}


def test_validate_accepts_valid_plant():
    power_plants.validate(SAMPLE)


def test_validate_rejects_bad_coords_capacity_and_fuel():
    bad = json.loads(json.dumps(SAMPLE))
    bad["plants"][0][0] = 95
    with pytest.raises(IngestError):
        power_plants.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["plants"][0][2] = -1
    with pytest.raises(IngestError):
        power_plants.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["plants"][0][3] = len(power_plants.FUELS)
    with pytest.raises(IngestError):
        power_plants.validate(bad)


def test_validate_rejects_unknown_fuel_enum_and_duplicates():
    bad = json.loads(json.dumps(SAMPLE))
    bad["fuels"][0] = "Unknown"
    with pytest.raises(IngestError):
        power_plants.validate(bad)
    bad = json.loads(json.dumps(SAMPLE))
    bad["plants"].append(list(bad["plants"][0]))
    with pytest.raises(IngestError):
        power_plants.validate(bad)


def test_bundled_asset_is_clean_and_global():
    data = power_plants.load()
    assert len(data["plants"]) >= 28_000
    assert len(data["fuels"]) == len(power_plants.FUELS)
    assert all(0 <= p[3] < len(power_plants.FUELS) for p in data["plants"])
    assert all(-90 <= p[0] <= 90 and -180 <= p[1] <= 180 and p[2] > 0
               for p in data["plants"])
    # Both hemispheres and a wide fuel mix are present.
    assert any(p[0] > 0 for p in data["plants"]) and any(p[0] < 0 for p in data["plants"])
    assert len({p[3] for p in data["plants"]}) == len(power_plants.FUELS)


def test_static_endpoint_etag_304():
    client = TestClient(app)
    r = client.get("/api/v1/static/power-plants")
    assert r.status_code == 200
    assert r.headers.get("etag", "").startswith('"')
    assert len(r.json()["plants"]) >= 28_000
    r2 = client.get("/api/v1/static/power-plants",
                    headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
