"""SQLite connection management and ordered migrations.

SQLite runs in WAL mode with foreign keys and a busy timeout. A migration is
recorded in the ``migrations`` table so upgrades are idempotent and repeatable.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..config import get_settings

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
    CREATE TABLE IF NOT EXISTS migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
    );

    CREATE TABLE IF NOT EXISTS source_status (
        source_id TEXT PRIMARY KEY,
        last_attempt_at TEXT,
        last_success_at TEXT,
        last_error_code TEXT,
        details_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS datasets (
        dataset_id TEXT PRIMARY KEY,
        source_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        attribution TEXT NOT NULL DEFAULT '',
        license_url TEXT NOT NULL DEFAULT '',
        enabled INTEGER NOT NULL DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS snapshots (
        snapshot_id TEXT PRIMARY KEY,
        dataset_id TEXT NOT NULL REFERENCES datasets(dataset_id),
        identity_key TEXT NOT NULL,
        init_time TEXT,
        observed_start TEXT,
        observed_end TEXT,
        payload_version TEXT NOT NULL DEFAULT '1',
        state TEXT NOT NULL DEFAULT 'candidate',
        published_at TEXT,
        details_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(dataset_id, identity_key, payload_version)
    );
    CREATE INDEX IF NOT EXISTS idx_snapshots_published ON snapshots(published_at);
    CREATE INDEX IF NOT EXISTS idx_snapshots_dataset ON snapshots(dataset_id, state);

    CREATE TABLE IF NOT EXISTS frames (
        frame_id TEXT PRIMARY KEY,
        snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
        layer_id TEXT NOT NULL,
        level_type TEXT NOT NULL DEFAULT '',
        level_value REAL,
        valid_time TEXT NOT NULL,
        bbox_json TEXT NOT NULL DEFAULT '{}',
        grid_json TEXT NOT NULL DEFAULT '{}',
        fields_json TEXT NOT NULL DEFAULT '[]',
        manifest_json TEXT NOT NULL DEFAULT '{}',
        UNIQUE(snapshot_id, layer_id, level_type, level_value, valid_time)
    );
    CREATE INDEX IF NOT EXISTS idx_frames_layer_time ON frames(layer_id, valid_time);

    CREATE TABLE IF NOT EXISTS assets (
        asset_id TEXT PRIMARY KEY,
        frame_id TEXT REFERENCES frames(frame_id),
        role TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        media_type TEXT NOT NULL DEFAULT 'application/octet-stream',
        sha256 TEXT NOT NULL DEFAULT '',
        bytes INTEGER NOT NULL DEFAULT 0,
        details_json TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE IF NOT EXISTS active_snapshots (
        dataset_id TEXT PRIMARY KEY REFERENCES datasets(dataset_id),
        snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
        published_at TEXT
    );

    CREATE TABLE IF NOT EXISTS observations (
        observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
        station_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        observed_at TEXT NOT NULL,
        revision TEXT NOT NULL DEFAULT '1',
        received_at TEXT NOT NULL,
        lon REAL NOT NULL,
        lat REAL NOT NULL,
        values_json TEXT NOT NULL DEFAULT '{}',
        raw_ref TEXT NOT NULL DEFAULT '',
        UNIQUE(source_id, station_id, observed_at, revision)
    );
    CREATE INDEX IF NOT EXISTS idx_obs_time ON observations(observed_at);
    """),
]


def db_path() -> Path:
    settings = get_settings()
    return settings.data_root / "catalog" / "catalog.sqlite3"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=30, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def _statements(sql: str) -> list[str]:
    """Split a migration script into individual statements.

    sqlite3.executescript implicitly commits any open transaction, so each
    statement is executed separately inside BEGIN IMMEDIATE instead.
    """
    return [s.strip() for s in sql.split(";") if s.strip()]


def migrate(path: Path | None = None) -> list[int]:
    applied: list[int] = []
    con = connect(path)
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute("""CREATE TABLE IF NOT EXISTS migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
        )""")
        have = {int(r[0]) for r in con.execute("SELECT version FROM migrations")}
        for version, sql in MIGRATIONS:
            if version in have:
                continue
            for statement in _statements(sql):
                con.execute(statement)
            con.execute("INSERT INTO migrations(version) VALUES (?)", (version,))
            applied.append(version)
        con.execute("COMMIT")
    except Exception:
        try:
            con.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        con.close()
    return applied


@contextmanager
def transaction(con: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
