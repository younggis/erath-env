"""Shipping-density texture: EPSG:4326 alignment, size limits and ETag."""
import struct

import pytest
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import shipping_density
from earthsim.ingest.base import IngestError


def test_bundled_texture_dimensions_and_size():
    payload, meta = shipping_density.load_asset()
    assert len(payload) < 5 * 1024 * 1024
    width, height = struct.unpack(">II", payload[16:24])
    assert (width, height) == (4096, 2048)
    assert (meta["width"], meta["height"]) == (width, height)


def test_projection_alignment_is_equirectangular():
    _, meta = shipping_density.load_asset()
    assert meta["projection"] == "EPSG:4326"
    assert meta["bounds"] == [-180.0, -90.0, 180.0, 90.0]
    px, py = meta["pixel_size_deg"]
    assert px == pytest.approx(360 / 4096, abs=1e-9)
    assert py == pytest.approx(180 / 2048, abs=1e-9)
    # Global bounds must cover exactly the texture grid, with no half-pixel shift.
    assert 360 / px == pytest.approx(4096, abs=1e-6)
    assert 180 / py == pytest.approx(2048, abs=1e-6)
    # Longitude 180W/0/180E and latitude 90N/0/90S map to grid corners/centre.
    assert shipping_density.lonlat_to_pixel(-180, 90) == (0, 0)
    assert shipping_density.lonlat_to_pixel(0, 0) == (2048, 1024)
    assert shipping_density.lonlat_to_pixel(180, -90) == (4096, 2048)


def test_validate_rejects_bad_texture_and_metadata():
    payload, meta = shipping_density.load_asset()
    bad = bytearray(payload)
    bad[16:20] = struct.pack(">I", 2048)
    with pytest.raises(IngestError):
        shipping_density.validate(bytes(bad), meta)
    with pytest.raises(IngestError):
        shipping_density.validate(payload, dict(meta, projection="EPSG:3857"))
    with pytest.raises(IngestError):
        shipping_density.validate(b"x" * (5 * 1024 * 1024 + 1), meta)
    with pytest.raises(IngestError):
        shipping_density.validate(payload, dict(meta, bounds=[-180, -90, 180, 85]))


def test_static_endpoint_serves_png_with_etag_304():
    client = TestClient(app)
    r = client.get("/api/v1/static/shipping-density")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/png")
    assert r.headers.get("etag", "").startswith('"')
    assert r.content[:8] == shipping_density.PNG_SIGNATURE
    r2 = client.get("/api/v1/static/shipping-density",
                    headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
