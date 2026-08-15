"""Request/response models for the VLM server API (blueprint §11.1)."""
from __future__ import annotations

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    model_id: str


class NavigationActionResponse(BaseModel):
    action: str
    raw_text: str
    latency_ms: float
    model_id: str
    parse_ok: bool
