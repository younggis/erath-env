"""CelesTrak NORAD GP/TLE cache for satellite orbit rendering.

Fetches only a few named groups (stations / weather / starlink) and caches them
with a TTL so the public upstream is never polled at high frequency.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from ..config import get_settings
from .base import IngestError, mark_failure, mark_success

log = logging.getLogger(__name__)

SOURCE_ID = "celestrak"
BASE_URL = "https://celestrak.org/NORAD/elements/gp.php"
GROUPS = ("stations", "weather", "starlink")
DEFAULT_TTL_SECONDS = 7200

_cache: dict[str, dict[str, Any]] = {}


def _cache_path(group: str):
    return get_settings().data_root / "raw" / "space" / f"tle_{group}.json"


def _ensure_loaded(group: str) -> None:
    """Seed the in-memory cache from the last good payload on disk."""
    if group in _cache:
        return
    path = _cache_path(group)
    if not path.exists():
        return
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(entry, dict) and entry.get("tles"):
            _cache[group] = entry
    except (OSError, ValueError):
        pass


def parse_tle_text(text: str) -> list[dict]:
    """Parse 3-line (name + L1 + L2) or bare 2-line TLE sets."""
    lines = [line.rstrip("\r\n") for line in text.splitlines() if line.strip()]
    records: list[dict] = []
    i = 0
    while i < len(lines) - 1:
        first, second = lines[i], lines[i + 1]
        name = ""
        if first.startswith("1 ") and second.startswith("2 "):
            line1, line2 = first, second
        elif i + 2 < len(lines) and lines[i + 1].startswith("1 ") and lines[i + 2].startswith("2 "):
            name, line1, line2 = first.strip(), lines[i + 1], lines[i + 2]
            i += 1
        else:
            i += 1
            continue
        norad = line1[2:7].strip()
        if not norad.isdigit():
            i += 1
            continue
        records.append({"name": name or f"NORAD {norad}", "norad_id": norad,
                        "line1": line1, "line2": line2})
        i += 2
    return records


def fetch_group(group: str, fetcher: Callable[[str, dict], str] | None = None) -> str:
    if group not in GROUPS:
        raise IngestError("BAD_GROUP", f"未知 TLE 分组：{group}")
    if fetcher is None:
        from .base import fetch
        result = fetch(BASE_URL, params={"GROUP": group, "FORMAT": "tle"}, timeout=45)
        return result.payload.decode("utf-8", errors="replace")
    return fetcher(BASE_URL, {"GROUP": group, "FORMAT": "tle"})


def refresh_group(group: str, fetcher: Callable[[str, dict], str] | None = None) -> dict:
    text = fetch_group(group, fetcher)
    records = parse_tle_text(text)
    if not records:
        raise IngestError("EMPTY_TLE", f"{group} 未返回有效 TLE")
    for record in records:
        record["group"] = group
    entry = {"tles": records, "fetched_at": time.time(), "group": group}
    _cache[group] = entry
    path = _cache_path(group)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return entry


def is_fresh(group: str, ttl_seconds: int | None = None) -> bool:
    _ensure_loaded(group)
    entry = _cache.get(group)
    if not entry:
        return False
    ttl = ttl_seconds if ttl_seconds is not None else get_settings().tle_cache_ttl_seconds
    return (time.time() - float(entry["fetched_at"])) < max(1, int(ttl))


def get_tles(groups: list[str] | None = None,
             fetcher: Callable[[str, dict], str] | None = None,
             force: bool = False, cached_only: bool = False) -> dict:
    selected = list(groups or GROUPS)
    for group in selected:
        _ensure_loaded(group)
    payload: list[dict] = []
    meta: dict[str, dict] = {}
    for group in selected:
        if group not in GROUPS:
            continue
        if not cached_only and (force or not is_fresh(group)):
            try:
                refresh_group(group, fetcher)
            except Exception as e:  # noqa: BLE001
                log.warning("TLE refresh failed for %s: %s", group, e)
                mark_failure(SOURCE_ID, e if hasattr(e, "code") else IngestError("FETCH_FAILED", str(e)))
        entry = _cache.get(group)
        if entry:
            payload.extend(entry["tles"])
            meta[group] = {"count": len(entry["tles"]),
                           "fetched_at": entry["fetched_at"],
                           "fresh": is_fresh(group)}
    return {"satellites": payload, "count": len(payload), "groups": meta,
            "source_url": BASE_URL}


def status() -> dict:
    return {group: {"count": len(_cache.get(group, {}).get("tles", [])),
                    "fresh": is_fresh(group),
                    "fetched_at": _cache.get(group, {}).get("fetched_at")}
            for group in GROUPS}


def refresh() -> dict:
    result = get_tles(force=True)
    if result["count"] == 0:
        mark_failure(SOURCE_ID, IngestError("NO_TLE", "未获取到任何 TLE"))
        return {"ok": False, "error": "NO_TLE"}
    mark_success(SOURCE_ID, {"count": result["count"], "groups": result["groups"]})
    return {"ok": True, "count": result["count"]}
