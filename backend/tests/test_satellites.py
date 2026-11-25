"""CelesTrak adapter: TLE parsing, TTL cache and refresh."""
from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import satellites

TLE = (
    "ISS (ZARYA)\n"
    "1 25544U 98067A   26327.91294507  .00005691  00000+0  10921-3 0  9993\n"
    "2 25544  51.6322 229.6520 0007379  58.6021 301.5689 15.49568558596519\n"
    "NOAA 19\n"
    "1 33591U 09005A   26328.01020304  .00000123  00000+0  12345-4 0  9991\n"
    "2 33591  99.1800  12.3456 0001234  45.6789 314.1234 14.12345678901234\n"
)


def test_parse_tle_text():
    rows = satellites.parse_tle_text(TLE)
    assert len(rows) == 2
    assert rows[0]["name"] == "ISS (ZARYA)" and rows[0]["norad_id"] == "25544"
    assert rows[0]["line1"].startswith("1 ") and rows[0]["line2"].startswith("2 ")
    assert rows[1]["norad_id"] == "33591"


def test_parse_tle_ignores_garbage():
    assert satellites.parse_tle_text("not a tle\nrandom text\n") == []


def test_cache_ttl_and_expiry_refresh(monkeypatch):
    satellites._cache.clear()
    now = {"t": 1000.0}
    monkeypatch.setattr(satellites.time, "time", lambda: now["t"])
    calls = []

    def fake(url, params):
        calls.append(params["GROUP"])
        return TLE

    first = satellites.get_tles(groups=["stations"], fetcher=fake)
    assert first["count"] == 2 and first["groups"]["stations"]["fresh"] is True
    assert calls == ["stations"]

    second = satellites.get_tles(groups=["stations"], fetcher=fake)
    assert second["count"] == 2 and calls == ["stations"]  # cache hit, no upstream call

    now["t"] += 7201  # past the 2h TTL
    third = satellites.get_tles(groups=["stations"], fetcher=fake)
    assert third["count"] == 2 and calls == ["stations", "stations"]


def test_tle_cache_survives_process_restart():
    satellites._cache.clear()
    satellites.refresh_group("weather", fetcher=lambda url, params: TLE)
    satellites._cache.clear()  # simulate an API restart
    data = satellites.get_tles(groups=["weather"],
                               fetcher=lambda url, params: (_ for _ in ()).throw(
                                   AssertionError("disk cache should avoid upstream")))
    assert data["count"] >= 2
    assert data["groups"]["weather"]["fetched_at"] > 0


def test_cached_only_never_calls_upstream():
    satellites._cache.clear()
    satellites.refresh_group("stations", fetcher=lambda url, params: TLE)
    data = satellites.get_tles(groups=["stations"], cached_only=True,
                               fetcher=lambda url, params: (_ for _ in ()).throw(
                                   AssertionError("cached_only must not fetch")))
    assert data["count"] >= 2


def test_tle_endpoint_returns_cached_satellites():
    satellites._cache.clear()
    satellites.refresh_group("stations", fetcher=lambda url, params: TLE)
    client = TestClient(app)
    r = client.get("/api/v1/space/tle", params={"groups": "stations"})
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 2
    sat = data["satellites"][0]
    assert sat["norad_id"].isdigit()
    assert sat["line1"].startswith("1 ") and sat["line2"].startswith("2 ")
