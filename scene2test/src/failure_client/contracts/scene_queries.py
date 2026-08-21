"""Revision-aware scene query contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import VersionedContractModel
from .resources import ResourceRef, RobotRef


class SceneQueryRequest(VersionedContractModel):
    scene: ResourceRef
    query_id: str = Field(min_length=1)
    query_version: str = Field(default="1.0", min_length=1)
    coordinate_frame: str = "scene"
    robot: RobotRef | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)


class SceneQueryResult(VersionedContractModel):
    scene: ResourceRef
    query_id: str = Field(min_length=1)
    query_implementation_version: str = Field(min_length=1)
    result: dict[str, Any] = Field(default_factory=dict)

