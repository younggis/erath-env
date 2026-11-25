"""Preprocessed OpenFlights route network static asset (offline-safe).

The bundled JSON contains deduplicated routes touching the busiest hubs, with
only the airports those routes need. Served with ETag revalidation.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from ..config import get_settings
from .base import IngestError

log = logging.getLogger(__name__)

SOURCE_ID = "openflights"
ASSET_NAME = "flight_routes.json"
SOURCE_URL = "https://github.com/jpatokal/openflights"
BUNDLED = Path(__file__).resolve().parent.parent / "static" / ASSET_NAME


def validate(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("airports"), dict):
        raise IngestError("BAD_ROUTES", "航线资产格式错误")
    if not isinstance(data.get("routes"), list) or not data["routes"]:
        raise IngestError("EMPTY_ROUTES", "航线资产为空")
    airports = data["airports"]
    seen = set()
    for code, info in airports.items():
        if not isinstance(info, dict):
            raise IngestError("BAD_ROUTES", "机场记录格式错误")
        lat, lon = info.get("lat"), info.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise IngestError("BAD_ROUTES", "机场经纬度缺失")
        if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            raise IngestError("BAD_ROUTES", f"机场 {code} 坐标超出 EPSG:4326")
    for pair in data["routes"]:
        if not isinstance(pair, list) or len(pair) != 2:
            raise IngestError("BAD_ROUTES", "航线记录格式错误")
        a, b = pair
        if a not in airports or b not in airports or a == b:
            raise IngestError("BAD_ROUTES", "航线引用了无效或相同机场")
        key = tuple(sorted((a, b)))
        if key in seen:
            raise IngestError("BAD_ROUTES", f"重复航线：{key}")
        seen.add(key)


def _cache_path() -> Path:
    return get_settings().data_root / "static" / ASSET_NAME


def load() -> dict:
    for path in (_cache_path(), BUNDLED):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            validate(data)
            return data
        except (OSError, ValueError, IngestError) as e:
            log.warning("route asset %s unusable: %s", path, e)
    raise IngestError("NO_ROUTE_DATA", "缺少航线静态资产")


def read_asset() -> tuple[bytes, str] | None:
    payload = json.dumps(load(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'
