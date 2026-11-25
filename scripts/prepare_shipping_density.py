"""Generate the global shipping-density night-glow texture.

Source: World Bank Global Shipping Traffic Density (multi-year AIS aggregate),
``shipdensity_global.zip``.  The archive bundles a 9.8 GB base raster plus an
external BigTIFF overview pyramid (``shipdensity_global.tif.ovr``).  Only a
coarse overview level is needed for a 4096x2048 globe texture, so the base
raster is never materialised.

The published archive is ~535 MB, but the overview member is fully contained
in its first ~140 MB.  Without a local archive the script fetches only that
prefix plus the ZIP tail (central directory) via HTTP byte ranges.

Output:
  backend/earthsim/static/shipping_density.png   (4096x2048, 8-bit grayscale)
  backend/earthsim/static/shipping_density.json  (projection / bounds metadata)

Usage:
  python scripts/prepare_shipping_density.py [--zip PATH]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
import rasterio
from rasterio.warp import Resampling, reproject

SOURCE_URL = ("https://datacatalogfiles.worldbank.org/ddh-published/0037580/"
              "DR0045406/shipdensity_global.zip")
ARCHIVE_SIZE = 534_907_276
OVR_NAME = "shipdensity_global.tif.ovr"
TFW_NAME = "shipdensity_global.tfw"
PREFIX_BYTES = 146_800_640   # 140 MB: covers the whole compressed overview
TAIL_BYTES = 1_000_000       # ZIP central directory

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "backend" / "earthsim" / "static"
TMP = REPO / ".local-data" / "tmp"
WIDTH, HEIGHT = 4096, 2048
OUT_BOUNDS = [-180.0, -90.0, 180.0, 90.0]
PIXEL = 360.0 / WIDTH
TARGET_OVERVIEW_WIDTH = 4501


def _curl_range(url: str, start: int, end: int, dest: Path) -> None:
    """Fetch an inclusive byte range with curl (fallback: urllib)."""
    cmd = ["curl.exe", "-sL", "--retry", "3", "--max-time", "600",
           "-r", f"{start}-{end}", "-o", str(dest), url]
    r = subprocess.run(cmd, check=False)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < (end - start) // 2:
        import urllib.request
        req = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end}"})
        dest.write_bytes(urllib.request.urlopen(req, timeout=600).read())


def obtain_zip(path: Path) -> Path:
    """Return a ZIP that at least contains the overview member and directory."""
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if OVR_NAME in names and TFW_NAME in names:
                return path
    except (zipfile.BadZipFile, OSError):
        pass

    head, tail = path.with_suffix(".head.bin"), path.with_suffix(".tail.bin")
    if not head.exists():
        _curl_range(SOURCE_URL, 0, PREFIX_BYTES - 1, head)
    if not tail.exists():
        _curl_range(SOURCE_URL, ARCHIVE_SIZE - TAIL_BYTES, ARCHIVE_SIZE - 1, tail)
    sparse = path.with_name("shipping_sparse.zip")
    with open(sparse, "wb") as f:
        f.truncate(ARCHIVE_SIZE)
    h, t = head.read_bytes(), tail.read_bytes()
    with open(sparse, "r+b") as f:
        f.seek(0)
        f.write(h)
        f.seek(ARCHIVE_SIZE - len(t))
        f.write(t)
    return sparse


def extract_overview(z: zipfile.ZipFile, dest: Path) -> None:
    """Stream the BigTIFF overview member to a local file."""
    if dest.exists() and dest.stat().st_size > 1_000_000_000:
        return
    with z.open(OVR_NAME) as src, open(dest, "wb") as out:
        while True:
            chunk = src.read(1 << 22)
            if not chunk:
                break
            out.write(chunk)


def open_overview(path: Path):
    """Open the GDAL directory holding the ~4501x2125 overview level."""
    for idx in range(1, 13):
        try:
            ds = rasterio.open(f"GTIFF_DIR:{idx}:{path}")
        except rasterio.RasterioIOError:
            continue
        if 3500 <= ds.width <= 5500:
            return ds
        ds.close()
    raise RuntimeError("no suitable overview level found")


def stretch(arr: np.ndarray) -> Image.Image:
    """Log-stretch AIS counts into a smooth 8-bit glow mask."""
    positive = arr[arr > 0]
    hi = float(np.log1p(positive).max()) if positive.size else 1.0
    # 99.5th percentile keeps extreme port counts from flattening the lanes.
    hi = float(np.percentile(np.log1p(positive), 99.5)) if positive.size else hi
    g = np.clip(np.log1p(np.clip(arr, 0, None)) / max(hi, 1e-6), 0, 1) ** 0.85
    img = Image.fromarray(np.round(g * 255).astype(np.uint8), mode="L")
    return img.filter(ImageFilter.GaussianBlur(radius=0.8))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, help="local World Bank shipdensity_global.zip")
    args = ap.parse_args()

    TMP.mkdir(parents=True, exist_ok=True)
    zip_path = obtain_zip(args.zip or TMP / "shipdensity_global.zip")
    with zipfile.ZipFile(zip_path) as z:
        tfw = [float(v) for v in z.read(TFW_NAME).decode().split()]
        ovr_path = TMP / OVR_NAME
        extract_overview(z, ovr_path)

    with open_overview(ovr_path) as ds:
        arr = ds.read(1)
        factor = 72_000 / ds.width       # base raster is 72000 px wide
    pixel = abs(tfw[0]) * factor
    src_transform = rasterio.transform.from_origin(
        tfw[4], tfw[5], pixel, pixel)

    dst_transform = rasterio.transform.from_origin(-180, 90, PIXEL, PIXEL)
    dst = np.zeros((HEIGHT, WIDTH), dtype=np.float32)
    with rasterio.io.MemoryFile() as mem:
        with mem.open(driver="GTiff", width=arr.shape[1], height=arr.shape[0],
                      count=1, dtype="int32", crs="EPSG:4326",
                      transform=src_transform, nodata=2_147_483_647) as sds:
            sds.write(arr, 1)
        with mem.open() as sds:
            reproject(rasterio.band(sds, 1), dst,
                      src_transform=src_transform, src_crs="EPSG:4326",
                      dst_transform=dst_transform, dst_crs="EPSG:4326",
                      src_nodata=2_147_483_647, dst_nodata=0,
                      resampling=Resampling.bilinear)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png = OUT_DIR / "shipping_density.png"
    stretch(dst).save(png, optimize=True)

    meta = {
        "source": "World Bank Global Shipping Traffic Density (multi-year AIS aggregate)",
        "source_url": SOURCE_URL,
        "projection": "EPSG:4326",
        "width": WIDTH,
        "height": HEIGHT,
        "bounds": OUT_BOUNDS,
        "pixel_size_deg": [360.0 / WIDTH, 180.0 / HEIGHT],
        "encoding": "8-bit grayscale PNG, log-scaled AIS density; 0 = no traffic",
    }
    (OUT_DIR / "shipping_density.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {png} ({png.stat().st_size} bytes) from {arr.shape[1]}x{arr.shape[0]} overview")


if __name__ == "__main__":
    main()
