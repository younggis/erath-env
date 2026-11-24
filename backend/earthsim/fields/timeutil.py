"""Time and longitude conventions.

All persisted/API times are ISO-8601 UTC with second precision. Longitudes are
normalized to [-180, 180). Forecast init/valid/lead are validated together.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

UTC = timezone.utc


def parse_iso(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("time must be an ISO-8601 string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    dt = dt.astimezone(UTC).replace(microsecond=0)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def normalize_lon(lon: float) -> float:
    """Normalize longitude into [-180, 180)."""
    lon = ((lon + 180.0) % 360.0) - 180.0
    # Avoid returning +180 which is the same meridian as -180.
    if lon >= 180.0:
        lon -= 360.0
    return lon


def normalize_lat(lat: float) -> float:
    return max(-90.0, min(90.0, float(lat)))


def gfs_cycles(now: datetime | None = None, count: int = 6) -> list[datetime]:
    """Candidate GFS cycle times (00/06/12/18Z), newest first."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    base = now.replace(hour=(now.hour // 6) * 6, minute=0, second=0, microsecond=0)
    return [base - timedelta(hours=6 * i) for i in range(count)]


def valid_from_lead(init: datetime, lead_hours: float) -> datetime:
    return init + timedelta(hours=float(lead_hours))


def lead_from_valid(init: datetime, valid: datetime) -> float:
    return (valid.astimezone(UTC) - init.astimezone(UTC)).total_seconds() / 3600.0


def validate_forecast(init: datetime, valid: datetime, lead_hours: float | None = None) -> float:
    lead = lead_from_valid(init, valid)
    if lead < 0:
        raise ValueError("valid_time must not precede init_time")
    if lead_hours is not None and abs(lead - float(lead_hours)) > 1e-6:
        raise ValueError("lead_hours is inconsistent with init_time/valid_time")
    return lead


def hour_range(start: datetime, end: datetime, step_hours: float = 1.0) -> list[datetime]:
    out: list[datetime] = []
    cur = start.astimezone(UTC)
    end = end.astimezone(UTC)
    delta = timedelta(hours=step_hours)
    while cur <= end:
        out.append(cur)
        cur += delta
    return out
