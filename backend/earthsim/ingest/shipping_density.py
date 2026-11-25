"""Bundled World Bank global shipping-density night-glow texture.

The 4096x2048 8-bit grayscale PNG is generated from the World Bank AIS
shipping-density raster by ``scripts/prepare_shipping_density.py``.  Its
georeferencing is checked against the bundled sidecar metadata before it is
served, so a misaligned or oversized texture cannot silently ship.
"""
from __future__ import annotations

import hashlib
import json
import logging
import struct
from pathlib import Path
from typing import Any

from ..config import get_settings
from .base import IngestError

log = logging.getLogger(__name__)

SOURCE_ID = "worldbank_shipping_density"
SOURCE_URL = ("https://datacatalogfiles.worldbank.org/ddh-published/0037580/"
              "DR0045406/shipdensity_global.zip")
ASSET_NAME = "shipping_density.png"
META_NAME = "shipping_density.json"
EXPECTED_SIZE = (4096, 2048)
MAX_BYTES = 5 * 1024 * 1024
EXPECTED_BOUNDS = [-180.0, -90.0, 180.0, 90.0]

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def validate(payload: bytes, meta: Any) -> None:
    """Check PNG dimensions/encoding, georeferencing and file size."""
    if len(payload) > MAX_BYTES:
        raise IngestError("SHIPPING_TEXTURE_TOO_LARGE", "海运密度纹理超过 5MB")
    if len(payload) < 33 or payload[:8] != PNG_SIGNATURE or payload[12:16] != b"IHDR":
        raise IngestError("BAD_SHIPPING_TEXTURE", "海运密度纹理不是有效 PNG")
    width, height, depth, color = struct.unpack(">IIBB", payload[16:26])
    if (width, height) != EXPECTED_SIZE:
        raise IngestError("BAD_SHIPPING_TEXTURE", f"纹理尺寸错误：{width}x{height}")
    if depth != 8 or color != 0:
        raise IngestError("BAD_SHIPPING_TEXTURE", "纹理必须是 8-bit 灰度 PNG")

    if not isinstance(meta, dict):
        raise IngestError("BAD_SHIPPING_META", "纹理元数据格式错误")
    if meta.get("projection") != "EPSG:4326":
        raise IngestError("BAD_SHIPPING_META", "纹理投影不是 EPSG:4326")
    bounds = meta.get("bounds")
    if not isinstance(bounds, list) or len(bounds) != 4:
        raise IngestError("BAD_SHIPPING_META", "纹理范围缺失")
    if [float(v) for v in bounds] != EXPECTED_BOUNDS:
        raise IngestError("BAD_SHIPPING_META", "纹理范围不是全球 -180..180 / -90..90")
    if (meta.get("width"), meta.get("height")) != EXPECTED_SIZE:
        raise IngestError("BAD_SHIPPING_META", "元数据尺寸与纹理不一致")
    px = meta.get("pixel_size_deg")
    if not isinstance(px, list) or len(px) != 2:
        raise IngestError("BAD_SHIPPING_META", "纹理像元尺寸缺失")
    if abs(float(px[0]) - 360 / EXPECTED_SIZE[0]) > 1e-9:
        raise IngestError("BAD_SHIPPING_META", "经度像元尺寸未对齐")
    if abs(float(px[1]) - 180 / EXPECTED_SIZE[1]) > 1e-9:
        raise IngestError("BAD_SHIPPING_META", "纬度像元尺寸未对齐")


def lonlat_to_pixel(lon: float, lat: float) -> tuple[int, int]:
    """EPSG:4326 -> texture pixel; u=0 at 180W, v=0 at 90N (image top)."""
    x = (lon + 180.0) / 360.0 * EXPECTED_SIZE[0]
    y = (90.0 - lat) / 180.0 * EXPECTED_SIZE[1]
    return int(x), int(y)


def _paths() -> tuple[Path, Path]:
    cache = get_settings().data_root / "static"
    png = cache / ASSET_NAME if (cache / ASSET_NAME).exists() else STATIC_DIR / ASSET_NAME
    meta_path = cache / META_NAME if (cache / META_NAME).exists() else STATIC_DIR / META_NAME
    return png, meta_path


def load_asset() -> tuple[bytes, dict]:
    png, meta_path = _paths()
    try:
        payload = png.read_bytes()
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        validate(payload, meta)
        return payload, meta
    except (OSError, ValueError, IngestError) as e:
        log.warning("shipping texture unusable: %s", e)
        raise IngestError("NO_SHIPPING_TEXTURE", "缺少有效的海运密度纹理资产") from e


def read_asset() -> tuple[bytes, str] | None:
    payload, _ = load_asset()
    return payload, '"' + hashlib.sha256(payload).hexdigest() + '"'
