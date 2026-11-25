"""Preprocess Natural Earth river / lake centreline GeoJSON for the globe.

Source: Natural Earth 1:50m Rivers + Lake Centerlines (scale_rank variant),
https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_50m_rivers_lake_centerlines_scale_rank.geojson

Keeps only LineString/MultiLineString geometry plus the fields used by the
shader (``scalerank``, ``strokeweig``, ``featurecla``, ``name``) and rounds
coordinates to 4 decimals (~11 m).  Topology checks: coordinates in
EPSG:4326, >=2 points per line and no antimeridian-spanning jumps.

Usage: python scripts/prepare_rivers.py [--geojson PATH]
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
from pathlib import Path

SOURCE_URL = ("https://api.github.com/repos/nvkelso/natural-earth-vector/contents/"
              "geojson/ne_50m_rivers_lake_centerlines_scale_rank.geojson")
REPO = Path(__file__).resolve().parent.parent
TMP = REPO / ".local-data" / "tmp" / "rivers.geojson"
OUT = REPO / "backend" / "earthsim" / "static" / "rivers.json"


def download(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["curl.exe", "-sL", "--retry", "3", "--max-time", "180",
                        "-H", "Accept: application/vnd.github.raw",
                        "-o", str(dest), SOURCE_URL], check=False)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 100_000:
        raise RuntimeError("Natural Earth river GeoJSON download failed")


def preprocess(src: dict) -> tuple[dict, int]:
    features = []
    dropped = 0
    for f in src.get("features", []):
        g = f.get("geometry") or {}
        p = f.get("properties") or {}
        if g.get("type") not in ("LineString", "MultiLineString"):
            dropped += 1
            continue
        try:
            rank = int(p["scalerank"])
            weight = float(p["strokeweig"])
        except (ValueError, KeyError, TypeError):
            dropped += 1
            continue
        if weight <= 0:
            dropped += 1
            continue
        lines = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        clean = []
        ok = True
        for line in lines:
            pts = []
            prev = None
            for xy in line:
                lon, lat = round(float(xy[0]), 4), round(float(xy[1]), 4)
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    ok = False
                    break
                if prev:
                    dx = abs(lon - prev[0])
                    dx = min(dx, 360 - dx)
                    if math.hypot(dx, lat - prev[1]) > 90:
                        ok = False
                        break
                pts.append([lon, lat])
                prev = (lon, lat)
            if len(pts) < 2:
                ok = False
                break
            clean.append(pts)
        if not ok:
            dropped += 1
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "MultiLineString" if len(clean) > 1 else "LineString",
                         "coordinates": clean if len(clean) > 1 else clean[0]},
            "properties": {
                "scalerank": rank,
                "strokeweig": round(weight, 3),
                "featurecla": str(p.get("featurecla") or "River"),
                "name": p.get("name"),
            },
        })
    return {"type": "FeatureCollection", "features": features}, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--geojson", type=Path, default=TMP)
    args = ap.parse_args()
    if not args.geojson.exists():
        download(args.geojson)
    data, dropped = preprocess(json.loads(args.geojson.read_text(encoding="utf-8")))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"wrote {OUT}: {len(data['features'])} features, {dropped} dropped, "
          f"{OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
