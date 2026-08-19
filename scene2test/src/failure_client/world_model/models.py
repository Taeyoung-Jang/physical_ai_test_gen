"""Minimal task-conditioned world model used by initial Client methods."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from failure_client.contracts import (
    ContractModel,
    ResourceSelection,
    TaskSpec,
    VersionedContractModel,
)


class TaskConditionedWorldModel(VersionedContractModel):
    task: TaskSpec
    resources: ResourceSelection
    scene_id: str
    scene_revision: str
    bounds: dict[str, Any] = Field(default_factory=dict)
    robot_profile: dict[str, Any] = Field(default_factory=dict)
    relevant_objects: list[dict[str, Any]] = Field(default_factory=list)
    relevant_regions: list[dict[str, Any]] = Field(default_factory=list)
    spawn_points: list[dict[str, Any]] = Field(default_factory=list)
    query_facts: dict[str, Any] = Field(default_factory=dict)
    known_failure_regions: list[dict[str, Any]] = Field(default_factory=list)
    uncertain_regions: list[dict[str, Any]] = Field(default_factory=list)


class WorldModelProjectionConfig(ContractModel):
    include_all_objects_when_unspecified: bool = True
    maximum_objects: int = Field(default=200, gt=0)

