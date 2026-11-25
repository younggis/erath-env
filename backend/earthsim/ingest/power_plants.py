"""Bundled WRI Global Power Plant Database (compact globe asset).

The JSON stores ``{fuels, plants: [[lat, lon, mw, fuelIndex, name]]}``.  Rows
with invalid coordinates, non-positive capacity or an unknown primary fuel are
removed by ``scripts/prepare_power_plants.py``; this module re-checks those
invariants before the asset is served.
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

SOURCE_ID = "wri_power_plants"
SOURCE_URL = "https://github.com/wri/global-power-plant-database"
ASSET_NAME = "power_plants.json"
BUNDLED = Path(__file__).resolve().parent.parent / "static" / ASSET_NAME

FUELS = (
    "Coal", "Gas", "Hydro", "Nuclear", "Oil", "Solar", "Wind", "Biomass",
    "Waste", "Geothermal", "Storage", "Other", "Cogeneration", "Petcoke",
    "Wave and Tidal",
)


def validate(data: Any) -> None:
    if not isinstance(data, dict) or not isinstance(data.get("plants"), list):
        raise IngestError("BAD_POWER_PLANTS", "电厂资产格式错误")
    fuels = data.get("fuels")
    if not isinstance(fuels, list) or len(fuels) != len(FUELS) or set(fuels) != set(FUELS):
        raise IngestError("BAD_FUEL_ENUM", "燃料类型枚举不完整")
    seen: set[tuple] = set()
    for row in data["plants"]:
        if not isinstance(row, list) or len(row) != 5:
            raise IngestError("BAD_POWER_PLANTS", "电厂记录格式错误")
        lat, lon, mw, fuel, name = row
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            raise IngestError("BAD_POWER_PLANTS", "电厂经纬度缺失")
        if not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            raise IngestError("BAD_POWER_PLANTS", f"电厂坐标超出 EPSG:4326：{lat},{lon}")
        if not isinstance(mw, (int, float)) or not (0 < float(mw) <= 1_000_000):
            raise IngestError("BAD_POWER_PLANTS", "装机容量无效")
        if not isinstance(fuel, int) or isinstance(fuel, bool) or not 0 <= fuel < len(FUELS):
            raise IngestError("BAD_FUEL_ENUM", f"燃料类型索引越界：{fuel}")
        if not isinstance(name, str):
            raise IngestError("BAD_POWER_PLANTS", "电厂名称格式错误")
        key = (round(float(lat), 4), round(float(lon), 4), round(float(mw), 1), fuel, name)
        if key in seen:
            raise IngestError("BAD_POWER_PLANTS", f"重复电厂：{name}")
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
            log.warning("power plant asset %s unusable: %s", path, e)
    raise IngestError("NO_POWER_PLANTS", "缺少电厂静态资产")


def read_asset() -> tuple[bytes, str] | None:
    payload = json.dumps(load(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'
