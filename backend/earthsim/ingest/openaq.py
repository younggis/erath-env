"""OpenAQ v3 ground-station air quality adapter.

Fetches paged global station metadata with the latest sensor values, converts
common gas units to µg/m³ and derives a PM2.5-based US AQI. Without an API key
the adapter degrades to a disabled status without any HTTP call.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo
from .base import IngestError, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "openaq"
DATASET_ID = "openaq-air-quality"
API_URL = "https://api.openaq.org/v3/locations"
MOLAR_MASS = {"no2": 46.01, "o3": 48.00, "so2": 64.07, "co": 28.01}
# 2024 US EPA PM2.5 breakpoints: (concentration hi, AQI hi)
PM25_BREAKPOINTS = ((9.0, 50), (35.4, 100), (55.4, 150),
                    (125.4, 200), (225.4, 300), (325.4, 400), (500.4, 500))
AQI_BREAKPOINTS = (50, 100, 150, 200, 300, 400, 500)


def normalize_unit(value: Any, unit: str | None, parameter: str) -> float | None:
    """Normalise a sensor reading to µg/m³ (SI-friendly mass concentration)."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    text = (unit or "").strip().lower().replace("μ", "u").replace("µ", "u")
    if "ug/m" in text or "ugm" in text:
        return round(number, 3)
    if "ppb" in text or "ppm" in text:
        factor = 1.0 if "ppb" in text else 1000.0
        mass = MOLAR_MASS.get(parameter)
        if mass is None:
            return None
        return round(number * factor * mass / 24.45, 3)
    # OpenAQ omits units for some PM sensors; their values are already µg/m³.
    if parameter.startswith("pm") and not text:
        return round(number, 3)
    return None


def pm25_aqi(concentration: float | None) -> int | None:
    """Piecewise-linear PM2.5 -> US AQI (0..500)."""
    if concentration is None or concentration < 0:
        return None
    low_c, low_a = 0.0, 0
    for (high_c, _), high_a in zip(PM25_BREAKPOINTS, AQI_BREAKPOINTS):
        if concentration <= high_c:
            return int(round(low_a + (concentration - low_c) /
                             max(1e-9, high_c - low_c) * (high_a - low_a)))
        low_c, low_a = high_c, high_a
    return 500


def _sensor_rows(raw: dict) -> list[tuple[str, str | None, Any, Any]]:
    rows = []
    for sensor in raw.get("sensors") or []:
        if not isinstance(sensor, dict):
            continue
        parameter = sensor.get("parameter") or {}
        name = str(parameter.get("name") or sensor.get("name") or "").lower()
        unit = parameter.get("units") or sensor.get("units")
        rows.append((name, unit, sensor.get("last_value"), sensor.get("last_datetime")))
    for param in raw.get("parameters") or []:
        if isinstance(param, dict):
            rows.append((str(param.get("name", "")).lower(), param.get("units"),
                         param.get("last_value"), param.get("last_datetime")))
    return rows


def parse_location(raw: dict, received: str) -> dict | None:
    lon, lat = raw.get("longitude"), raw.get("latitude")
    try:
        lon, lat = float(lon), float(lat)
    except (TypeError, ValueError):
        return None
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    values: dict[str, Any] = {}
    latest = ""
    for name, unit, value, when in _sensor_rows(raw):
        normalized = normalize_unit(value, unit, name)
        if normalized is None:
            continue
        values[f"{name}_ugm3"] = normalized
        if when and str(when) > latest:
            latest = str(when)
    if not values:
        return None
    values["aqi_pm25"] = pm25_aqi(values.get("pm25_ugm3"))
    station_id = str(raw.get("id") or f"{lon:.4f},{lat:.4f}")
    return {
        "station_id": f"openaq-{station_id}",
        "source_id": SOURCE_ID,
        "observed_at": to_iso(datetime.now(timezone.utc)),
        "received_at": received,
        "lon": lon, "lat": lat,
        "values": {**values, "station_name": raw.get("name", ""),
                   "sensor_time": latest or None},
        "raw_ref": "",
    }


def fetch_page(page: int, limit: int, fetcher: Callable[[str, dict, float], Any] | None = None,
               timeout: float = 30.0) -> dict:
    """Fetch one OpenAQ v3 page. Returns ``{results, found}``."""
    key = (get_settings().openaq_api_key or "").strip()
    if not key:
        raise IngestError("MISSING_API_KEY", "未配置 EARTHSIM_OPENAQ_API_KEY")
    if fetcher is None:
        import httpx
        def fetcher(url, params, t):
            with httpx.Client(timeout=t, follow_redirects=True,
                              headers={"X-API-Key": key}) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.text
    try:
        payload = fetcher(API_URL, {"limit": limit, "page": page}, timeout)
        if isinstance(payload, (bytes, bytearray)):
            payload = payload.decode("utf-8")
        if isinstance(payload, str):
            payload = json.loads(payload)
        results = payload.get("results", []) if isinstance(payload, dict) else []
        found = (payload.get("meta") or {}).get("found", len(results)) if isinstance(payload, dict) else len(results)
        return {"results": results, "found": int(found)}
    except Exception as e:  # noqa: BLE001
        raise IngestError("UPSTREAM_ERROR", f"OpenAQ 拉取失败：{e}") from e


def fetch_all(max_pages: int | None = None,
              fetcher: Callable[[str, dict, float], Any] | None = None) -> list[dict]:
    settings = get_settings()
    pages = max_pages or settings.openaq_max_pages
    limit = settings.openaq_page_size
    rows: list[dict] = []
    for page in range(1, pages + 1):
        batch = fetch_page(page, limit, fetcher)
        rows.extend(batch["results"])
        if len(batch["results"]) < limit:
            break
    return rows


def status() -> dict:
    key = (get_settings().openaq_api_key or "").strip()
    return {
        "enabled": bool(key), "configured": bool(key),
        "note": ("OpenAQ v3 全球空气质量监测站" if key
                 else "未配置 EARTHSIM_OPENAQ_API_KEY，OpenAQ 站点未启用"),
        "source_url": API_URL,
    }


def refresh(fetcher: Callable[[str, dict, float], Any] | None = None) -> dict:
    if not (get_settings().openaq_api_key or "").strip():
        return {"ok": False, "enabled": False, "error": "MISSING_API_KEY",
                "note": status()["note"]}
    try:
        received = to_iso(datetime.now(timezone.utc))
        rows = [r for raw in fetch_all(fetcher=fetcher)
                if (r := parse_location(raw, received)) is not None]
        if not rows:
            raise IngestError("NO_STATIONS", "OpenAQ 未返回有效站点")
        repo.insert_observations(rows)
        now = to_iso(datetime.now(timezone.utc))
        repo.ensure_dataset(DATASET_ID, SOURCE_ID, "observation",
                            "OpenAQ v3 全球地面空气质量监测站", "OpenAQ",
                            "https://openaq.org/")
        snap_id = f"openaq-{datetime.now(timezone.utc):%Y%m%dT%H%M}Z"
        repo.insert_snapshot({
            "snapshot_id": snap_id, "dataset_id": DATASET_ID,
            "identity_key": now, "init_time": now,
            "observed_start": now, "observed_end": now,
            "payload_version": "1", "state": "published", "published_at": now,
            "details": {"stations": len(rows)},
        }, [], publish=True)
        mark_success(SOURCE_ID, {"stations": len(rows)})
        return {"ok": True, "stations": len(rows)}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
