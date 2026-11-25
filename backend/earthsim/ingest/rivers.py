"""Bundled Natural Earth global river / lake centreline GeoJSON.

The asset keeps LineString/MultiLineString geometry and the
``scalerank`` / ``strokeweig`` attributes needed for graded glowing lines.
Topology and attribute completeness are checked before it is served.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path
from typing import Any

from ..config import get_settings
from .base import IngestError

log = logging.getLogger(__name__)

SOURCE_ID = "natural_earth_rivers"
SOURCE_URL = "https://www.naturalearthdata.com/downloads/50m-physical-vectors/"
ASSET_NAME = "rivers.json"
BUNDLED = Path(__file__).resolve().parent.parent / "static" / ASSET_NAME
REQUIRED_FIELDS = ("scalerank", "strokeweig", "featurecla", "name")


def validate(data: Any) -> None:
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection" \
            or not isinstance(data.get("features"), list) or not data["features"]:
        raise IngestError("BAD_RIVERS", "河湖中心线资产格式错误")
    for feature in data["features"]:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise IngestError("BAD_RIVERS", "水系 Feature 格式错误")
        geom = feature.get("geometry") or {}
        props = feature.get("properties") or {}
        gtype = geom.get("type")
        if gtype not in ("LineString", "MultiLineString"):
            raise IngestError("BAD_RIVER_TOPOLOGY", f"不支持的水系几何：{gtype}")
        for field in REQUIRED_FIELDS:
            if field not in props:
                raise IngestError("BAD_RIVER_PROPS", f"水系属性缺失：{field}")
        rank, weight = props["scalerank"], props["strokeweig"]
        if not isinstance(rank, int) or isinstance(rank, bool) or not 1 <= rank <= 12:
            raise IngestError("BAD_RIVER_PROPS", f"河流等级无效：{rank}")
        if not isinstance(weight, (int, float)) or not 0 < float(weight) <= 10:
            raise IngestError("BAD_RIVER_PROPS", f"线宽权重无效：{weight}")
        if not isinstance(props["featurecla"], str):
            raise IngestError("BAD_RIVER_PROPS", "要素类别格式错误")

        lines = [geom.get("coordinates")] if gtype == "LineString" else geom.get("coordinates")
        if not isinstance(lines, list) or not lines:
            raise IngestError("BAD_RIVER_TOPOLOGY", "水系坐标缺失")
        for line in lines:
            if not isinstance(line, list) or len(line) < 2:
                raise IngestError("BAD_RIVER_TOPOLOGY", "水系线段至少需要两个节点")
            prev = None
            for xy in line:
                if not isinstance(xy, list) or len(xy) != 2:
                    raise IngestError("BAD_RIVER_TOPOLOGY", "水系节点格式错误")
                lon, lat = float(xy[0]), float(xy[1])
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise IngestError("BAD_RIVER_TOPOLOGY", f"水系坐标超界：{lon},{lat}")
                if prev:
                    dx = abs(lon - prev[0])
                    dx = min(dx, 360 - dx)
                    if math.hypot(dx, lat - prev[1]) > 90:
                        raise IngestError("BAD_RIVER_TOPOLOGY", "水系线段跨越反经线")
                prev = (lon, lat)


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
            log.warning("river asset %s unusable: %s", path, e)
    raise IngestError("NO_RIVER_DATA", "缺少水系静态资产")


def read_asset() -> tuple[bytes, str] | None:
    payload = json.dumps(load(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'
