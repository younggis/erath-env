"""Shared HTTP client with bounded retry/backoff and source status updates."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import datetime, timezone
from typing import Callable

import httpx

from ..config import get_settings
from ..fields.timeutil import to_iso
from ..catalog import repository as repo


def safe_url(url: str) -> str:
    """Strip credential-like query values before a URL enters logs/catalog."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    query = [
        (key, "***" if any(token in key.lower() for token in
                           ("key", "token", "secret", "api", "auth")) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(query), parts.fragment))


def retry_seconds(header: str | None, default: float) -> float:
    """Parse Retry-After (delta-seconds only; HTTP-date falls back to default)."""
    if header:
        try:
            return min(60.0, max(0.0, float(header)))
        except (TypeError, ValueError):
            pass
    return default


class IngestError(RuntimeError):
    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass
class FetchResult:
    payload: bytes
    url: str
    status_code: int
    etag: str | None
    attempts: int


def fetch(url: str, *, params: dict | None = None, max_attempts: int = 4,
          timeout: float | None = None, validator: Callable[[httpx.Response], None] | None = None) -> FetchResult:
    """GET with bounded retry and jitter for 429/503/5xx and connection errors.

    Respects Retry-After. 404 is returned immediately (unpublished candidate).
    Raises IngestError when all attempts fail.
    """
    s = get_settings()
    timeout = timeout or s.http_timeout_seconds
    headers = {"User-Agent": "earthsim/1.0 (local research simulator)"}
    last: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
                r = client.get(url, params=params)
            if r.status_code == 404:
                raise IngestError("SOURCE_NOT_FOUND", f"上游 404：{safe_url(url)}", {"url": safe_url(url)})
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == max_attempts:
                    raise IngestError("SOURCE_THROTTLED" if r.status_code == 429 else "SOURCE_ERROR",
                                      f"上游返回 {r.status_code}", {"url": safe_url(url), "status": r.status_code})
                delay = retry_seconds(r.headers.get("Retry-After"), float(min(2 ** attempt, 30)))
                time.sleep(delay + random.uniform(0, 0.5))
                continue
            if r.status_code >= 400:
                raise IngestError("SOURCE_ERROR", f"上游返回 {r.status_code}", {"url": safe_url(url), "status": r.status_code})
            if validator:
                validator(r)
            if len(r.content) > s.max_download_bytes:
                raise IngestError("SOURCE_TOO_LARGE", "下载超过字节上限", {"bytes": len(r.content)})
            return FetchResult(r.content, safe_url(str(r.url)), r.status_code, r.headers.get("ETag"), attempt)
        except IngestError:
            raise
        except (httpx.HTTPError, OSError) as e:
            last = e
            if attempt == max_attempts:
                break
            time.sleep(min(2 ** attempt, 30) + random.uniform(0, 0.5))
    raise IngestError("NETWORK_ERROR", f"连接失败：{last}", {"error": str(last)})


def mark_success(source_id: str, details: dict | None = None) -> None:
    # Use an aware UTC datetime: to_iso() calls astimezone(), which would
    # otherwise interpret a naive UTC value as local time (8h shift in UTC+8).
    repo.upsert_source(source_id, success=True, at=to_iso(datetime.now(timezone.utc)), details=details)


def mark_failure(source_id: str, err: IngestError) -> None:
    repo.upsert_source(source_id, success=False, at=to_iso(datetime.now(timezone.utc)),
                       error_code=err.code, details={"message": str(err), **err.details})
