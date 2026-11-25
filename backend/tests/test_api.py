"""Service integration tests using Starlette's TestClient."""
from fastapi.testclient import TestClient

from earthsim.api.app import app

client = TestClient(app)


def test_health_and_layers():
    r = client.get("/api/v1/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    layers = client.get("/api/v1/layers").json()["layers"]
    ids = {l["layer_id"] for l in layers}
    assert {"wind10", "temp2m", "rh2m", "mslp", "cloud_total", "visibility_sfc"} <= ids
    assert all(l["state"] == "published" for l in layers)


def test_frames_manifest_asset_and_sample():
    fr = client.get("/api/v1/layers/wind10/frames").json()
    assert fr["frames"] and fr["snapshot_id"]
    fid = "test-wind10-t03"
    m = client.get(f"/api/v1/frames/{fid}").json()
    assert m["schema_version"] == 1 and m["grid"]["nx"] == 9
    adr = m["assets"][0]["href"]
    a = client.get(adr)
    assert a.status_code == 200
    assert a.headers.get("etag")
    assert client.get(adr, headers={"If-None-Match": a.headers["etag"]}).status_code == 304

    s = client.get("/api/v1/sample", params={"frame_id": fid, "lon": 0, "lat": 0}).json()
    assert s["sampling_method"] == "bilinear"
    assert any(v["id"] == "wind" for v in s["values"])
    assert s["values"][0]["value"] is not None


def test_stations_and_errors():
    r = client.get("/api/v1/stations", params={"bbox": "100,20,150,50", "at": "2026-11-20T03:00:00Z"})
    assert r.status_code == 200 and "RJTT" in [s["station_id"] for s in r.json()["stations"]]
    bad = client.get("/api/v1/frames/does-not-exist")
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "FRAME_NOT_FOUND"
    badbbox = client.get("/api/v1/stations", params={"bbox": "bad"})
    assert badbbox.status_code == 422
