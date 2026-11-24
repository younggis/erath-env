"""Pydantic v2 request/response schemas."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody


class SampleResponse(BaseModel):
    frame_id: str
    lon: float
    lat: float
    valid_time: str
    values: list[dict[str, Any]]
    sampling_method: str
    quality: dict[str, Any] = Field(default_factory=dict)
    source_kind: str = ""
    note: str | None = None
