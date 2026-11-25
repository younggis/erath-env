"""Tectonic plate boundary GeoJSON (fraxen/tectonicplates, public domain).

A simplified GeoJSON is bundled in the package so the layer works fully
offline / in fixture mode; the API serves it with ETag revalidation.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings
from .base import IngestError, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "tectonics"
ASSET_NAME = "tectonic_plates.json"
SOURCE_URL = ("https://raw.githubusercontent.com/fraxen/tectonicplates/master/"
              "GeoJSON/PB2002_boundaries.json")
BUNDLED = Path(__file__).resolve().parent.parent / "static" / ASSET_NAME


def validate_geojson(data: Any) -> None:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise IngestError("BAD_GEOJSON", "板块边界不是 FeatureCollection")
    features = data.get("features")
    if not isinstance(features, list) or not features:
        raise IngestError("EMPTY_GEOJSON", "板块边界无要素")
    for feature in features:
        geometry = (feature or {}).get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise IngestError("BAD_GEOJSON", "板块边界线段坐标不足")
        for pair in coords:
            if not isinstance(pair, (list, tuple)) or len(pair) < 2:
                raise IngestError("BAD_GEOJSON", "板块边界坐标格式错误")
            lon, lat = pair[0], pair[1]
            if not (-180 <= float(lon) <= 180 and -90 <= float(lat) <= 90):
                raise IngestError("BAD_GEOJSON", "板块边界坐标超出 EPSG:4326")


def _cache_path() -> Path:
    return get_settings().data_root / "static" / ASSET_NAME


def load_geojson() -> dict:
    """Load from the data-root cache first, then the bundled offline asset."""
    for path in (_cache_path(), BUNDLED):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validate_geojson(data)
            return data
        except (OSError, ValueError, IngestError) as e:
            log.warning("tectonic asset %s unusable: %s", path, e)
    raise IngestError("NO_TECTONIC_DATA", "缺少板块边界 GeoJSON 资产")


def read_asset() -> tuple[bytes, str] | None:
    data = load_geojson()
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'


def simplify(data: dict) -> dict:
    features = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "LineString":
            continue
        features.append({
            "type": "Feature",
            "properties": {k: props.get(k, "") for k in ("Name", "PlateA", "PlateB", "Type")},
            "geometry": {"type": "LineString",
                         "coordinates": [[round(float(c[0]), 3), round(float(c[1]), 3)]
                                         for c in geometry.get("coordinates", [])]},
        })
    out = {"type": "FeatureCollection", "name": "tectonic_plates", "features": features}
    validate_geojson(out)
    return out


def refresh(fetcher: Any = None) -> dict:
    try:
        if fetcher is None:
            from .base import fetch
            payload = fetch(SOURCE_URL, timeout=90).payload
        else:
            payload = fetcher(SOURCE_URL)
        data = json.loads(payload.decode("utf-8") if isinstance(payload, (bytes, bytearray)) else str(payload))
        simplified = simplify(data)
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.part")
        tmp.write_text(json.dumps(simplified, ensure_ascii=False, separators=(",", ":")),
                       encoding="utf-8")
        tmp.replace(path)
        mark_success(SOURCE_ID, {"features": len(simplified["features"])})
        return {"ok": True, "features": len(simplified["features"])}
    except Exception as e:  # noqa: BLE001
        err = e if isinstance(e, IngestError) else IngestError("FETCH_FAILED", str(e))
        mark_failure(SOURCE_ID, err)
        return {"ok": False, "error": err.code}
