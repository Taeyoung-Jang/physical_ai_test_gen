"""Methodology-neutral intervention contract."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel


class InterventionSpec(ContractModel):
    operation_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    operation_version: str = Field(default="1.0", min_length=1)
    coordinate_frame: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)

