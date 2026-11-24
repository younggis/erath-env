"""NOAA NDBC real-time ocean buoy adapter.

Reads the public fixed-width latest-observations text stream and normalises it
the same way as METAR: SI units, ``MM`` / sentinel missing markers become
``None``, timestamps become UTC ISO-8601. Observations are stored in the shared
``observations`` table with ``source_id=noaa_ndbc``.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "noaa_ndbc"
DATASET_ID = "noaa-ndbc"
API_URL = "https://www.ndbc.noaa.gov/data/latest_obs/latest_obs.txt"
MISSING_MARKERS = {"", "MM", "M", "NA", "N/A", "-", "9999", "9999.0"}

# Column order of the header line in latest_obs.txt.
COLUMNS = (
    "station_id", "lat", "lon", "year", "month", "day", "hour", "minute",
    "wind_dir", "wind_speed", "gust", "wave_height", "dominant_period",
    "average_period", "mean_wave_dir", "pressure", "pressure_tendency",
    "air_temp", "water_temp", "dewpoint", "visibility", "tide",
)


def parse_missing(raw: str | None) -> float | None:
    """Convert NDBC missing markers and unparsable tokens to ``None``."""
    if raw is None:
        return None
    token = str(raw).strip()
    if token.upper() in MISSING_MARKERS:
        return None
    try:
        value = float(token)
    except ValueError:
        return None
    # NDBC uses large sentinels for missing in some feeds.
    if abs(value) >= 9999:
        return None
    return value


def normalize(line: str, received: str) -> dict | None:
    """Normalise one NDBC data row; return ``None`` for unusable lines."""
    text = line.strip()
    if not text or text.startswith("#"):
        return None
    parts = text.split()
    if len(parts) < 19:
        return None
    row = {name: (parts[i] if i < len(parts) else "") for i, name in enumerate(COLUMNS)}

    lat = parse_missing(row["lat"])
    lon = parse_missing(row["lon"])
    station_id = str(row["station_id"]).strip()
    if not station_id or lat is None or lon is None:
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    try:
        observed = datetime(
            int(float(row["year"])), int(float(row["month"])), int(float(row["day"])),
            int(float(row["hour"])), int(float(row["minute"])), tzinfo=timezone.utc,
        )
    except (ValueError, TypeError):
        return None

    values = {
        "wind_direction_deg": parse_missing(row["wind_dir"]),
        "wind_speed_ms": parse_missing(row["wind_speed"]),
        "gust_ms": parse_missing(row["gust"]),
        "wave_height_m": parse_missing(row["wave_height"]),
        "dominant_wave_period_s": parse_missing(row["dominant_period"]),
        "mean_wave_direction_deg": parse_missing(row["mean_wave_dir"]),
        "pressure_hpa": parse_missing(row["pressure"]),
        "pressure_tendency_hpa": parse_missing(row["pressure_tendency"]),
        "air_temp_c": parse_missing(row["air_temp"]),
        "water_temp_c": parse_missing(row["water_temp"]),
        "dewpoint_c": parse_missing(row["dewpoint"]),
        "visibility_nmi": parse_missing(row["visibility"]),
    }
    return {
        "station_id": station_id,
        "source_id": SOURCE_ID,
        "observed_at": to_iso(observed),
        "revision": "1",
        "received_at": received,
        "lon": lon,
        "lat": lat,
        "values": values,
        "raw_ref": "raw/ndbc/latest_obs.txt",
    }


def parse_text(text: str, received: str | None = None) -> list[dict]:
    received = received or to_iso(datetime.now(timezone.utc))
    rows = []
    seen = set()
    for line in text.splitlines():
        station = normalize(line, received)
        if station and station["station_id"] not in seen:
            seen.add(station["station_id"])
            rows.append(station)
    return rows


def refresh() -> dict:
    try:
        result = fetch(API_URL, timeout=60)
        text = result.payload.decode("utf-8", errors="replace")
        rows = parse_text(text)
        if len(rows) < 100:
            raise IngestError("TOO_FEW_STATIONS", f"NDBC 有效站点仅 {len(rows)} 个")

        root = get_settings().data_root
        path = root / "raw/ndbc/latest_obs.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        tmp = path.with_suffix(".txt.part")
        tmp.write_bytes(raw)
        tmp.replace(path)

        inserted = repo.insert_observations(rows)
        snap_id = f"noaa-ndbc-{datetime.now(timezone.utc):%Y%m%dT%H%M}Z"
        now = to_iso(datetime.now(timezone.utc))
        repo.ensure_dataset(DATASET_ID, SOURCE_ID, "observation",
                            "NOAA NDBC 全球海洋浮标实时观测", "NOAA NDBC",
                            "https://www.ndbc.noaa.gov/")
        repo.insert_snapshot({
            "snapshot_id": snap_id, "dataset_id": DATASET_ID,
            "identity_key": now, "init_time": now, "observed_start": now,
            "observed_end": now, "payload_version": "1", "state": "published",
            "published_at": now,
            "details": {"stations": inserted, "source_url": result.url,
                        "sha256": hashlib.sha256(raw).hexdigest()},
        }, [], publish=True)
        mark_success(SOURCE_ID, {"stations": inserted, "source_url": result.url})
        return {"ok": True, "stations": inserted, "snapshot_id": snap_id}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
