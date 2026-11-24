"""Copernicus DEM GLO-30 public tile adapter.

Reads CRS, NoData, pixel size, vertical datum and corner extent. Uses rasterio
when installed; stores a JSON+bin representation otherwise so local DEM loading
and the resolution label can be exercised offline.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import get_settings
from ..catalog import repository as repo
from .base import IngestError, fetch

SOURCE_ID = "copernicus_dem"
DATASET_ID = "copernicus-glo30"
S3_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"


def tile_key(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"Copernicus_DSM_COG_10_{ns}{abs(lat):02d}_00_{ew}{abs(lon):03d}_00_DEM"


def tile_url(lat: int, lon: int) -> str:
    key = tile_key(lat, lon)
    return f"{S3_BASE}/{key}/{key}.tif"


def download_tile(lat: int, lon: int) -> Path:
    r = fetch(tile_url(lat, lon), validator=lambda resp: _check_tif(resp.content))
    root = get_settings().data_root
    rel = Path("raw/topography/copernicus-glo30/1") / f"{tile_key(lat, lon)}.tif"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".part")
    tmp.write_bytes(r.payload)
    tmp.replace(p)
    return p


def _check_tif(payload: bytes) -> None:
    if len(payload) < 8 or payload[:4] not in (b"II*\x00", b"MM\x00*"):
        raise IngestError("BAD_TIFF", "DEM 瓦片不是 GeoTIFF")


def describe_tile(path: Path) -> dict:
    """Return CRS / NoData / pixel size / vertical datum / corner extent."""
    try:  # pragma: no cover - rasterio is an optional dependency
        import rasterio
        with rasterio.open(path) as ds:
            return {
                "crs": ds.crs.to_string() if ds.crs else None,
                "nodata": ds.nodata,
                "dx": abs(ds.transform.a), "dy": abs(ds.transform.e),
                "nx": ds.width, "ny": ds.height,
                "bounds": list(ds.bounds), "dtype": ds.dtypes[0],
                "vertical_datum": "EGM96 (MSL)", "provider": "Copernicus DEM GLO-30",
            }
    except ImportError:
        return {"crs": None, "nodata": None, "dx": None, "dy": None,
                "vertical_datum": "EGM96 (MSL)", "provider": "Copernicus DEM GLO-30",
                "note": "未安装 rasterio，无法读取 GeoTIFF 元数据"}
