"""Revision-pinned resource and scene snapshot contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, VersionedContractModel


class ResourceRef(ContractModel):
    id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class RobotRef(ResourceRef):
    profile_id: str = Field(min_length=1)


class ResourceSelection(ContractModel):
    scene: ResourceRef
    robot: RobotRef
    controller: ResourceRef
    policy: ResourceRef | None = None


class CoordinateSystem(ContractModel):
    up_axis: str = "Z"
    unit: str = "meter"


class SceneSnapshot(VersionedContractModel):
    scene_id: str = Field(min_length=1)
    scene_revision: str = Field(min_length=1)
    coordinate_system: CoordinateSystem = Field(default_factory=CoordinateSystem)
    bounds: dict[str, Any] = Field(default_factory=dict)
    objects: list[dict[str, Any]] = Field(default_factory=list)
    regions: list[dict[str, Any]] = Field(default_factory=list)
    spawn_points: list[dict[str, Any]] = Field(default_factory=list)
    cameras: list[dict[str, Any]] = Field(default_factory=list)
    query_capabilities: list[str] = Field(default_factory=list)
    intervention_capabilities: list[str] = Field(default_factory=list)

