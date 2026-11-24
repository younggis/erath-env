"""TeleGeography Submarine Cable Map GeoJSON cache.

Cables and landing points are cached to the data root and served by an API
endpoint with strong ETag / 304 support so the browser can revalidate cheaply.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings
from .base import IngestError, fetch, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "telegeography"
CABLE_URL = "https://www.submarinecablemap.com/api/v3/cable/cable-geo.json"
LANDING_URL = "https://www.submarinecablemap.com/api/v3/landing-point/landing-point-geo.json"
ASSETS = {"cables": CABLE_URL, "landing": LANDING_URL}


def validate_geojson(data: Any, name: str) -> None:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise IngestError("BAD_GEOJSON", f"{name} 不是 FeatureCollection")
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise IngestError("EMPTY_GEOJSON", f"{name} 无要素")
    checked = 0
    for feature in features:
        geometry = feature.get("geometry") or {}
        gtype = geometry.get("type")
        coords = geometry.get("coordinates")
        if gtype not in ("LineString", "MultiLineString", "Point", "MultiPoint"):
            continue
        if not isinstance(coords, list) or not coords:
            raise IngestError("BAD_GEOJSON", f"{name} 几何坐标缺失")
        checked += 1
    if checked == 0:
        raise IngestError("BAD_GEOJSON", f"{name} 无有效线/点几何")


def _path(name: str) -> Path:
    return get_settings().data_root / "static" / f"submarine_{name}.json"


def read_asset(name: str) -> tuple[bytes, str] | None:
    if name not in ASSETS:
        return None
    path = _path(name)
    if not path.exists():
        return None
    payload = path.read_bytes()
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'


def refresh(etcher: Any = None) -> dict:
    try:
        total = 0
        for name, url in ASSETS.items():
            if etcher is not None:
                payload = etcher(url)
            else:
                payload = fetch(url, timeout=90).payload
            text = payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload)
            data = json.loads(text)
            validate_geojson(data, name)
            path = _path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.part")
            tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(path)
            total += len(data.get("features", []))
        mark_success(SOURCE_ID, {"features": total})
        return {"ok": True, "features": total}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
