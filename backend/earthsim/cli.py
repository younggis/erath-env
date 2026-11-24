"""Reproducible command-line entry points (guide section 8.3)."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from .config import get_settings, REPO_ROOT
from .catalog import repository as repo
from .fields.timeutil import to_iso
from .ingest import disasters, fixtures, gfs, metar, dem


def cmd_doctor(args) -> int:
    s = get_settings()
    root = s.data_root
    print("EarthSim doctor")
    print(f"  version         : 1.0.0")
    print(f"  data mode       : {s.data_mode}")
    print(f"  repo root       : {REPO_ROOT}")
    print(f"  data root       : {root}")
    print(f"  free disk       : {shutil.disk_usage(str(root)).free / 1024**3:.1f} GiB")
    print(f"  python          : {sys.version.split()[0]}")
    try:
        import numpy
        print(f"  numpy           : {numpy.__version__}")
    except Exception:
        pass
    for name in ("numpy", "httpx", "fastapi", "uvicorn"):
        print(f"  module {name:<10}: {'ok' if __import__(name) else 'missing'}")
    for name in ("eccodes", "satpy", "rasterio", "netCDF4"):
        try:
            mod = __import__(name)
            print(f"  optional {name:<8}: {getattr(mod, '__version__', 'present')}")
        except Exception:
            print(f"  optional {name:<8}: not installed (offline/limited mode)")
    try:
        repo.ensure_migrated()
        print("  catalog         : ok (WAL, migrations applied)")
    except Exception as e:
        print(f"  catalog         : FAILED {e}")
        return 1
    return 0


def cmd_fixtures(args) -> int:
    if args.action == "install":
        result = fixtures.install_all()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"fixtures installed into {get_settings().data_root}")
    elif args.action == "verify":
        result = fixtures.verify_all()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    return 0


def cmd_sources(args) -> int:
    if args.action == "probe":
        result = {"gfs_cycle": None, "metar": None, "dem": "requires live run"}
        try:
            result["gfs_cycle"] = to_iso(gfs.probe_latest()) if gfs.probe_latest() else None
        except Exception as e:
            result["gfs_cycle"] = f"error: {e}"
        try:
            result["metar"] = metar.refresh([m[0] for m in fixtures.STATIONS[:2]])
        except Exception as e:
            result["metar"] = f"error: {e}"
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.action == "refresh":
        from .ingest import cams, firms, gefs, hrrr, ifs, ndbc, oisst, openaq, realtime, volume, wave
        fn = {"noaa_gfs": gfs.refresh,
              "hrrr": hrrr.refresh, "ecmwf_ifs": ifs.refresh,
              "gfs_volume": volume.refresh,
              "noaa_wave": wave.refresh,
              "noaa_oisst": oisst.refresh,
              "cams": cams.refresh,
              "noaa_gefs": gefs.refresh,
              "noaa_ndbc": ndbc.refresh,
              "nasa_firms": firms.refresh,
              "openaq": openaq.refresh,
              "awc_metar": metar.refresh,
              "usgs_quake": realtime.refresh_quakes, "opensky": realtime.refresh_flights,
              "nhc_storm": realtime.refresh_storms, "nasa_cme": realtime.refresh_cme,
              "noaa_aurora": realtime.refresh_aurora, "noaa_solar_wind": realtime.refresh_solar_wind,
              "gdacs": disasters.refresh_gdacs, "eonet": disasters.refresh_eonet,
              "nasa_firms": disasters.refresh_firms,
              "realtime_all": realtime.refresh}.get(args.source)
        if not fn:
            print(f"unknown source {args.source}", file=sys.stderr)
            return 2
        print(json.dumps(fn(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"sources": repo.get_sources()}, ensure_ascii=False, indent=2))
    return 0


def cmd_catalog(args) -> int:
    if args.action == "stats":
        with repo.connect() as con:
            stats = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in (
                "datasets", "snapshots", "frames", "assets", "observations")}
        print(json.dumps(stats, indent=2))
    elif args.action == "cleanup":
        root = get_settings().data_root
        with repo.connect() as con:
            active = {r[0] for r in con.execute("SELECT snapshot_id FROM active_snapshots")}
            candidates = [dict(r) for r in con.execute(
                "SELECT snapshot_id FROM snapshots WHERE state='candidate'")]
            stale = [s["snapshot_id"] for s in candidates if s["snapshot_id"] not in active]
            paths: list[str] = []
            for sid in stale:
                for a in con.execute(
                        """SELECT a.relative_path FROM assets a
                           JOIN frames f ON a.frame_id=f.frame_id WHERE f.snapshot_id=?""", (sid,)):
                    paths.append(a["relative_path"])
        # tmp files older than 24 h
        tmp_root = root / "tmp"
        now = time.time()
        tmp_files = []
        if tmp_root.exists():
            for p in tmp_root.rglob("*"):
                if p.is_file() and now - p.stat().st_mtime > 86400:
                    tmp_files.append(str(p.relative_to(root)))
        targets = paths + tmp_files
        est = sum((root / p).stat().st_size for p in targets if (root / p).exists())
        if args.dry_run:
            print(json.dumps({"dry_run": True, "targets": targets[:50],
                              "target_count": len(targets), "estimated_bytes": est,
                              "protected": {"active_snapshots": len(active)}},
                             ensure_ascii=False, indent=2))
        else:
            for p in targets:
                (root / p).unlink(missing_ok=True)
            with repo.connect() as con:
                for sid in stale:
                    con.execute("DELETE FROM assets WHERE frame_id IN (SELECT frame_id FROM frames WHERE snapshot_id=?)", (sid,))
                    con.execute("DELETE FROM frames WHERE snapshot_id=?", (sid,))
                    con.execute("DELETE FROM snapshots WHERE snapshot_id=?", (sid,))
            print(json.dumps({"dry_run": False, "removed": len(targets),
                              "freed_bytes": est}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="earthsim", description="Earth Environment Simulator CLI")
    sub = p.add_subparsers(dest="group")
    doctor = sub.add_parser("doctor"); doctor.set_defaults(func=cmd_doctor)
    fx = sub.add_parser("fixtures"); fx.add_argument("action", choices=["install", "verify"]); fx.set_defaults(func=cmd_fixtures)
    src = sub.add_parser("sources")
    src.add_argument("action", choices=["probe", "refresh", "status"])
    src.add_argument("--source", default="noaa_gfs")
    src.set_defaults(func=cmd_sources)
    cat = sub.add_parser("catalog")
    cat.add_argument("action", choices=["stats", "cleanup"])
    cat.add_argument("--dry-run", action="store_true")
    cat.set_defaults(func=cmd_catalog)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
