"""Catalog atomicity, replay and source status tests."""
from earthsim.catalog import repository as repo
from earthsim.catalog.db import migrate, db_path
from earthsim.config import get_settings
from earthsim.ingest import fixtures


def test_migrations_idempotent():
    assert migrate() == []
    assert db_path().exists()


def test_fixtures_installed_and_checksums_ok():
    result = fixtures.verify_all()
    assert result["ok"], result["problems"]
    assert result["checked"] > 100


def test_publish_is_atomic_and_active_pointer_single():
    ds = "test-dataset"
    repo.ensure_dataset(ds, "test", "forecast")
    base = {"dataset_id": ds, "payload_version": "1"}
    # candidate batch does not change the active pointer
    repo.insert_snapshot({**base, "snapshot_id": "snap-candidate", "identity_key": "cand",
                          "init_time": "2026-11-20T00:00:00Z", "state": "candidate"}, [])
    assert repo.get_active_snapshot(ds) is None
    # published batch becomes visible in one transaction
    repo.insert_snapshot({**base, "snapshot_id": "snap-live", "identity_key": "live",
                          "init_time": "2026-11-21T00:00:00Z",
                          "state": "published", "published_at": "2026-11-21T00:00:00Z"}, [], publish=True)
    assert repo.get_active_snapshot(ds)["snapshot_id"] == "snap-live"
    repo.publish_snapshot("snap-candidate", "2026-11-22T00:00:00Z")
    assert repo.get_active_snapshot(ds)["snapshot_id"] == "snap-candidate"


def test_frame_and_asset_lookup():
    frames = repo.list_frames("wind10", "fixture-gfs-20261120T0000Z")
    assert len(frames) == 25
    f = repo.get_frame(frames[3]["frame_id"])
    assert f["layer_id"] == "wind10" and len(f["assets"]) == 1
    a = repo.get_asset(f["assets"][0]["asset_id"])
    assert repo.asset_path(a).exists()


def test_source_status_and_observations():
    repo.upsert_source("test-source", success=True, at="2026-11-20T00:00:00Z")
    repo.upsert_source("bad-source", success=False, at="2026-11-20T00:00:00Z", error_code="NETWORK_ERROR")
    src = {s["source_id"]: s for s in repo.get_sources()}
    assert src["test-source"]["last_error_code"] is None
    assert src["bad-source"]["last_error_code"] == "NETWORK_ERROR"
    obs = repo.query_stations(None, "2026-11-20T03:00:00Z", 200)
    assert any(o["station_id"] == "RJTT" for o in obs)
