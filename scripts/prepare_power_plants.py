"""Preprocess the WRI Global Power Plant Database into a compact asset.

Source: https://github.com/wri/global-power-plant-database
(output_database/global_power_plant_database.csv)

Only the fields needed for the globe are kept, stored as parallel arrays so
35k plants stay small: ``{fuels, plants: [[lat, lon, mw, fuelIndex, name]]}``.
Rows with invalid coordinates, non-positive capacity or an unknown fuel are
dropped; exact duplicates are removed.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from pathlib import Path

SOURCE_URL = ("https://raw.githubusercontent.com/wri/global-power-plant-database/"
              "master/output_database/global_power_plant_database.csv")
FUELS = (
    "Coal", "Gas", "Hydro", "Nuclear", "Oil", "Solar", "Wind", "Biomass",
    "Waste", "Geothermal", "Storage", "Other", "Cogeneration", "Petcoke",
    "Wave and Tidal",
)
FUEL_INDEX = {name: i for i, name in enumerate(FUELS)}

REPO = Path(__file__).resolve().parent.parent
TMP = REPO / ".local-data" / "tmp" / "global_power_plant_database.csv"
OUT = REPO / "backend" / "earthsim" / "static" / "power_plants.json"


def download(dest: Path) -> None:
    r = subprocess.run(["curl.exe", "-sL", "--retry", "3", "--max-time", "240",
                        "-o", str(dest), SOURCE_URL], check=False)
    if r.returncode != 0 or not dest.exists() or dest.stat().st_size < 1_000_000:
        raise RuntimeError("WRI power plant CSV download failed")


def preprocess(csv_path: Path) -> tuple[dict, int]:
    plants: list[list] = []
    seen: set[tuple] = set()
    dropped = 0
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                lat, lon = float(row["latitude"]), float(row["longitude"])
                mw = float(row["capacity_mw"])
                fuel = FUEL_INDEX[row["primary_fuel"]]
            except (ValueError, KeyError, TypeError):
                dropped += 1
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or mw <= 0:
                dropped += 1
                continue
            name = (row.get("name") or "").strip()[:80]
            key = (round(lat, 4), round(lon, 4), round(mw, 1), fuel, name)
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            plants.append([round(lat, 4), round(lon, 4), round(mw, 1), fuel, name])
    return {"fuels": list(FUELS), "plants": plants}, dropped


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=TMP)
    args = ap.parse_args()
    if not args.csv.exists():
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        download(args.csv)
    data, dropped = preprocess(args.csv)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    print(f"wrote {OUT}: {len(data['plants'])} plants, {dropped} dropped, "
          f"{OUT.stat().st_size} bytes")


if __name__ == "__main__":
    main()
