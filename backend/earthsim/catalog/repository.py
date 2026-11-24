"""High-level catalog operations used by API, CLI and workers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from ..config import get_settings
from .db import connect, migrate, transaction


def _j(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def ensure_migrated() -> None:
    migrate()


# --------------------------------------------------------------------------- sources
def upsert_source(source_id: str, *, success: bool, at: str, error_code: str | None = None, details: dict | None = None) -> None:
    with connect() as con, transaction(con):
        if success:
            con.execute(
                """INSERT INTO source_status(source_id,last_attempt_at,last_success_at,last_error_code,details_json)
                   VALUES (?,?,?,NULL,?)
                   ON CONFLICT(source_id) DO UPDATE SET
                     last_attempt_at=excluded.last_attempt_at,
                     last_success_at=excluded.last_success_at,
                     last_error_code=NULL,
                     details_json=excluded.details_json""",
                (source_id, at, at, _j(details or {})),
            )
        else:
            con.execute(
                """INSERT INTO source_status(source_id,last_attempt_at,last_error_code,details_json)
                   VALUES (?,?,?,?)
                   ON CONFLICT(source_id) DO UPDATE SET
                     last_attempt_at=excluded.last_attempt_at,
                     last_error_code=excluded.last_error_code,
                     details_json=excluded.details_json""",
                (source_id, at, error_code or "UNKNOWN", _j(details or {})),
            )


def get_sources() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM source_status ORDER BY source_id")]


# --------------------------------------------------------------------------- datasets
def ensure_dataset(dataset_id: str, source_id: str, kind: str, description: str = "",
                   attribution: str = "", license_url: str = "", enabled: bool = True) -> None:
    with connect() as con, transaction(con):
        con.execute(
            """INSERT INTO datasets(dataset_id,source_id,kind,description,attribution,license_url,enabled)
               VALUES (?,?,?,?,?,?,?)
               ON CONFLICT(dataset_id) DO UPDATE SET
                 source_id=excluded.source_id, kind=excluded.kind,
                 description=excluded.description, attribution=excluded.attribution,
                 license_url=excluded.license_url, enabled=excluded.enabled""",
            (dataset_id, source_id, kind, description, attribution, license_url, int(enabled)),
        )


def get_datasets() -> list[dict]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM datasets ORDER BY dataset_id")]


# --------------------------------------------------------------------------- snapshots
def insert_snapshot(snapshot: dict, frames: list[dict], publish: bool = False) -> str:
    """Insert a snapshot with its frames/assets in one transaction.

    ``publish`` updates the active pointer atomically with the insert, which is
    how complete candidate batches become visible in a single switch.
    """
    sid = snapshot["snapshot_id"]
    with connect() as con, transaction(con):
        con.execute(
            """INSERT OR IGNORE INTO snapshots(snapshot_id,dataset_id,identity_key,init_time,
                 observed_start,observed_end,payload_version,state,published_at,details_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (sid, snapshot["dataset_id"], snapshot["identity_key"],
             snapshot.get("init_time"), snapshot.get("observed_start"), snapshot.get("observed_end"),
             snapshot.get("payload_version", "1"),
             "published" if publish else "candidate",
             snapshot.get("published_at") if publish else None,
             _j(snapshot.get("details", {}))),
        )
        for fr in frames:
            con.execute(
                """INSERT INTO frames(frame_id,snapshot_id,layer_id,level_type,level_value,
                     valid_time,bbox_json,grid_json,fields_json,manifest_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(frame_id) DO UPDATE SET
                     snapshot_id=excluded.snapshot_id, valid_time=excluded.valid_time,
                     bbox_json=excluded.bbox_json, grid_json=excluded.grid_json,
                     fields_json=excluded.fields_json, manifest_json=excluded.manifest_json""",
                (fr["frame_id"], sid, fr["layer_id"], fr.get("level_type", ""),
                 fr.get("level_value"), fr["valid_time"], _j(fr.get("bbox", {})),
                 _j(fr.get("grid", {})), _j(fr.get("fields", [])), _j(fr.get("manifest", {}))),
            )
            for asset in fr.get("assets", []):
                con.execute(
                    """INSERT OR REPLACE INTO assets(asset_id,frame_id,role,relative_path,media_type,sha256,bytes)
                       VALUES (?,?,?,?,?,?,?)""",
                    (asset["asset_id"], fr["frame_id"], asset.get("role", "grid"),
                     asset["relative_path"], asset.get("media_type", "application/octet-stream"),
                     asset.get("sha256", ""), int(asset.get("bytes", 0))),
                )
        if publish:
            published_at = snapshot.get("published_at")
            con.execute(
                """INSERT INTO active_snapshots(dataset_id,snapshot_id,published_at) VALUES (?,?,?)
                   ON CONFLICT(dataset_id) DO UPDATE SET
                     snapshot_id=excluded.snapshot_id, published_at=excluded.published_at""",
                (snapshot["dataset_id"], sid, published_at),
            )
    return sid


def publish_snapshot(snapshot_id: str, published_at: str) -> None:
    with connect() as con, transaction(con):
        row = con.execute("SELECT dataset_id FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        if not row:
            raise KeyError(snapshot_id)
        con.execute("UPDATE snapshots SET state='published', published_at=? WHERE snapshot_id=?",
                    (published_at, snapshot_id))
        con.execute(
            """INSERT INTO active_snapshots(dataset_id,snapshot_id,published_at) VALUES (?,?,?)
               ON CONFLICT(dataset_id) DO UPDATE SET
                 snapshot_id=excluded.snapshot_id, published_at=excluded.published_at""",
            (row["dataset_id"], snapshot_id, published_at),
        )


def get_active_snapshot(dataset_id: str) -> dict | None:
    with connect() as con:
        row = con.execute(
            """SELECT s.* FROM active_snapshots a JOIN snapshots s ON s.snapshot_id=a.snapshot_id
               WHERE a.dataset_id=?""", (dataset_id,)
        ).fetchone()
        return dict(row) if row else None


def get_snapshot(snapshot_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)).fetchone()
        return dict(row) if row else None


def list_snapshots(dataset_id: str | None = None, state: str | None = None) -> list[dict]:
    q = "SELECT * FROM snapshots WHERE 1=1"
    args: list[Any] = []
    if dataset_id:
        q += " AND dataset_id=?"; args.append(dataset_id)
    if state:
        q += " AND state=?"; args.append(state)
    q += " ORDER BY COALESCE(published_at, init_time, observed_start) DESC"
    with connect() as con:
        return [dict(r) for r in con.execute(q, args)]


# --------------------------------------------------------------------------- frames
def get_frame(frame_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM frames WHERE frame_id=?", (frame_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        for k in ("bbox_json", "grid_json", "fields_json", "manifest_json"):
            d[k[:-5]] = json.loads(d.pop(k))
        d["assets"] = [dict(a) for a in con.execute(
            "SELECT * FROM assets WHERE frame_id=? ORDER BY role", (frame_id,))]
        return d


def list_frames(layer_id: str | None = None, snapshot_id: str | None = None,
                valid_from: str | None = None, valid_to: str | None = None,
                limit: int | None = None) -> list[dict]:
    q = "SELECT frame_id,snapshot_id,layer_id,level_type,level_value,valid_time FROM frames WHERE 1=1"
    args: list[Any] = []
    if layer_id:
        q += " AND layer_id=?"; args.append(layer_id)
    if snapshot_id:
        q += " AND snapshot_id=?"; args.append(snapshot_id)
    if valid_from:
        q += " AND valid_time>=?"; args.append(valid_from)
    if valid_to:
        q += " AND valid_time<=?"; args.append(valid_to)
    q += " ORDER BY valid_time ASC"
    if limit:
        q += " LIMIT ?"; args.append(int(limit))
    with connect() as con:
        return [dict(r) for r in con.execute(q, args)]


def get_asset(asset_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
        return dict(row) if row else None


def asset_path(asset: dict) -> Path:
    return get_settings().data_root / asset["relative_path"]


def checksum(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- observations
def delete_observations_before(source_ids: Iterable[str], before_iso: str) -> int:
    """Drop stale real-time point events so the store does not grow unbounded."""
    ids = list(source_ids)
    if not ids:
        return 0
    marks = ",".join("?" for _ in ids)
    with connect() as con, transaction(con):
        cur = con.execute(
            f"DELETE FROM observations WHERE source_id IN ({marks}) AND observed_at < ?",
            (*ids, before_iso),
        )
        return cur.rowcount or 0


def insert_observations(rows: Iterable[dict]) -> int:
    rows = list(rows)
    with connect() as con, transaction(con):
        for r in rows:
            con.execute(
                """INSERT OR REPLACE INTO observations(station_id,source_id,observed_at,revision,
                     received_at,lon,lat,values_json,raw_ref)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (r["station_id"], r["source_id"], r["observed_at"], r.get("revision", "1"),
                 r["received_at"], r["lon"], r["lat"], _j(r.get("values", {})), r.get("raw_ref", "")),
            )
    return len(rows)


def query_stations(bbox: tuple[float, float, float, float] | None,
                   at: str | None, max_age_minutes: int = 120,
                   source_id: str | None = None) -> list[dict]:
    """Return each station's nearest observation within max_age_minutes of ``at``."""
    from ..fields.timeutil import parse_iso, to_iso
    from datetime import timedelta

    q = "SELECT * FROM observations WHERE 1=1"
    args: list[Any] = []
    if source_id:
        q += " AND source_id=?"; args.append(source_id)
    if bbox:
        w, s, e, n = bbox
        q += " AND lon>=? AND lon<=? AND lat>=? AND lat<=?"; args += [w, e, s, n]
    with connect() as con:
        rows = [dict(r) for r in con.execute(q, args)]
    if at:
        target = parse_iso(at)
        rows = [r for r in rows if abs((parse_iso(r["observed_at"]) - target).total_seconds()) <= max_age_minutes * 60]
    # keep newest per station
    newest: dict[str, dict] = {}
    for r in sorted(rows, key=lambda x: x["observed_at"]):
        newest[r["station_id"]] = r
    out = []
    for r in newest.values():
        r["values"] = json.loads(r.pop("values_json"))
        out.append(r)
    return sorted(out, key=lambda x: x["station_id"])
