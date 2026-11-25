"""Blitzortung lightning cache: window expiry, coordinate validation, backoff."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from earthsim.api.app import app
from earthsim.ingest import lightning


def test_backoff_delay_is_exponential_and_capped():
    assert lightning.backoff_delay(1, base=5) == 5
    assert lightning.backoff_delay(2, base=5) == 10
    assert lightning.backoff_delay(3, base=5) == 20
    assert lightning.backoff_delay(10, base=5, cap=30) == 30


def test_parse_strike_dict_and_array():
    rec = lightning.parse_strike({"id": "a1", "lon": 139.7, "lat": 35.6,
                                  "time": 1795564800})
    assert rec is not None and rec["id"] == "a1"
    assert rec["lon"] == 139.7 and rec["lat"] == 35.6
    assert rec["observed_at"].endswith("Z")

    array_rec = lightning.parse_strike([-79.8, 38.3, 1795564800, "b2"])
    assert array_rec is not None and array_rec["id"] == "b2"
    assert array_rec["lat"] == 38.3

    assert lightning.parse_strike({"lon": 999, "lat": 0, "time": 1}) is None
    assert lightning.parse_strike({"lon": 0, "lat": -91, "time": 1}) is None
    assert lightning.parse_strike(None) is None


def test_window_pruning_removes_expired_strikes():
    cache = lightning.LightningCache(window_minutes=5, max_strikes=100)
    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(minutes=25)).timestamp()
    new_ts = (now - timedelta(minutes=2)).timestamp()
    # Wide window during ingest so neither is pruned, then a narrow prune now.
    cache.window = timedelta(minutes=60)
    cache.ingest([
        {"id": "old", "lon": 10, "lat": 20, "time": old_ts},
        {"id": "new", "lon": 11, "lat": 21, "time": new_ts},
    ])
    assert cache.size() == 2
    cache.window = timedelta(minutes=5)
    removed = cache.prune(now)
    assert removed == 1
    assert [s["id"] for s in cache.snapshot()] == ["new"]


def test_cache_dedupes_and_caps():
    cache = lightning.LightningCache(window_minutes=60000, max_strikes=2)
    for i in range(4):
        cache.ingest([{"id": f"id{i}", "lon": i, "lat": i, "time": 1795564800 + i}])
    assert cache.size() == 2
    assert {s["id"] for s in cache.snapshot()} == {"id2", "id3"}


def test_safe_poll_never_raises_and_returns_backoff():
    def failing(url, timeout):
        raise OSError("network down")

    result = lightning.safe_poll(fetcher=failing, attempt=1)
    assert result["ok"] is False
    assert "network down" in result["error"]
    assert result["retry_after_seconds"] > 0


def test_failed_upstream_does_not_block_poller_thread():
    lightning._CACHE.clear()
    lightning.stop_poller()
    lightning._poll_thread = None

    def failing(url, timeout):
        raise OSError("down")

    original = lightning.fetch_strikes
    lightning.fetch_strikes = lambda *args, **kwargs: failing("", 1)
    try:
        assert lightning.start_poller(interval=0.01) is True
        thread = lightning._poll_thread
        assert thread is not None and thread.daemon is True
        assert thread.is_alive()
        lightning.stop_poller()
        thread.join(timeout=2)
        assert not thread.is_alive()
    finally:
        lightning.stop_poller()
        lightning.fetch_strikes = original


def test_lightning_endpoint_returns_valid_coords():
    lightning._CACHE.clear()
    now = datetime.now(timezone.utc).timestamp()
    lightning._CACHE.ingest([
        {"id": "x1", "lon": 139.7, "lat": 35.6, "time": now},
        {"id": "x2", "lon": -79.8, "lat": 38.3, "time": now - 60},
    ])
    client = TestClient(app)
    r = client.get("/api/v1/realtime/lightning")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] >= 2
    for strike in data["strikes"]:
        assert -180 <= strike["lon"] <= 180
        assert -90 <= strike["lat"] <= 90
