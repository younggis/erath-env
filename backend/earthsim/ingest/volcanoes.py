"""Global Holocene volcano catalogue (Smithsonian / NOAA NCEI, public).

A cleaned static asset is bundled in the package so the 3D volcano layer works
offline. `last_year` is derived from the Smithsonian era code
and is an approximate midpoint, not an exact eruption date.
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

SOURCE_ID = "volcanoes"
ASSET_NAME = "volcanoes.json"
SOURCE_URL = "https://raw.githubusercontent.com/plotly/datasets/master/volcano_db.csv"
BUNDLED = Path(__file__).resolve().parent.parent / "static" / ASSET_NAME


def validate(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("features"), list):
        raise IngestError("BAD_VOLCANO_DATA", "火山数据格式错误")
    if not data["features"]:
        raise IngestError("EMPTY_VOLCANO_DATA", "火山数据为空")
    for row in data["features"]:
        if not isinstance(row, dict):
            raise IngestError("BAD_VOLCANO_DATA", "火山记录格式错误")
        lon, lat = row.get("lon"), row.get("lat")
        elev = row.get("elev")
        if not isinstance(lon, (int, float)) or not isinstance(lat, (int, float)):
            raise IngestError("BAD_VOLCANO_DATA", "火山经纬度缺失")
        if not (-180 <= float(lon) <= 180 and -90 <= float(lat) <= 90):
            raise IngestError("BAD_VOLCANO_DATA", "火山经纬度超出 EPSG:4326")
        if not isinstance(elev, (int, float)) or not (-11000 <= float(elev) <= 10000):
            raise IngestError("BAD_VOLCANO_DATA", "火山海拔异常")


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
            log.warning("volcano asset %s unusable: %s", path, e)
    raise IngestError("NO_VOLCANO_DATA", "缺少火山静态资产")


def read_asset() -> tuple[bytes, str] | None:
    payload = json.dumps(load(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'
