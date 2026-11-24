"""OpenSky adapter: state vector parsing and 429 backoff."""
import pytest

from earthsim.catalog import repository as repo
from earthsim.ingest import opensky
from earthsim.ingest.base import IngestError

RECEIVED = "2026-11-25T02:00:00Z"


def _state(alt=11000.0, track=90.0, vr=3.5, lon=-0.5, lat=51.4):
    return ["abc123", "BAW123", "United Kingdom", 1764040800, 1764040800,
            lon, lat, alt, False, 230.0, track, vr]


def test_retry_delay_exponential_with_retry_after():
    assert opensky.retry_delay(1) == 2.0
    assert opensky.retry_delay(2) == 4.0
    assert opensky.retry_delay(3) == 8.0
    assert opensky.retry_delay(1, retry_after=30) == 30.0


def test_parse_states_preserves_si_fields_and_nulls():
    on_ground_state = ["g", "X", "C", 0, 0, 1, 2, None, True, 0, 0, 0]
    data = {"states": [_state(), _state(alt=None, track=None, vr=None, lon=10, lat=20),
                       on_ground_state]}
    rows = opensky.parse_states(data, RECEIVED)
    assert len(rows) == 2  # on-ground skipped
    first = rows[0]["values"]
    assert first["baro_altitude_m"] == 11000.0
    assert first["true_track_deg"] == 90.0
    assert first["vertical_rate_ms"] == 3.5
    second = rows[1]["values"]
    assert second["baro_altitude_m"] is None
    assert second["true_track_deg"] is None


def test_parse_states_rejects_bad_coords():
    assert opensky.parse_states({"states": [_state(lon=999)]}, RECEIVED) == []


def test_fetch_states_backs_off_on_429(monkeypatch):
    sleeps = []
    monkeypatch.setattr(opensky.time, "sleep", lambda s: sleeps.append(s))
    calls = []

    def fake(url):
        calls.append(url)
        if len(calls) < 3:
            return {"status_code": 429, "retry_after": None}
        return {"status_code": 200, "body": {"states": [_state()]}}

    data = opensky.fetch_states(fetcher=fake)
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]
    assert len(data["states"]) == 1


def test_fetch_states_raises_after_exhausted_retries(monkeypatch):
    monkeypatch.setattr(opensky.time, "sleep", lambda s: None)
    with pytest.raises(IngestError) as exc:
        opensky.fetch_states(fetcher=lambda url: {"status_code": 429}, attempts=2)
    assert exc.value.code == "SOURCE_THROTTLED"


def test_refresh_with_fixture_inserts_altitude():
    result = opensky.refresh(fetcher=lambda url: {
        "status_code": 200, "body": {"states": [_state()]}})
    assert result["ok"] is True and result["events"] == 1
    rows = repo.query_stations(None, None, source_id="opensky")
    assert rows and rows[0]["values"]["baro_altitude_m"] == 11000.0
