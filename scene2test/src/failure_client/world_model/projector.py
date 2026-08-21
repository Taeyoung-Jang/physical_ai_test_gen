"""Project remote snapshots into a small task-relevant Client representation."""

from __future__ import annotations

from typing import Any

from failure_client.contracts import CapabilitySnapshot, ResourceSelection, SceneSnapshot, TaskSpec

from .models import TaskConditionedWorldModel, WorldModelProjectionConfig


class WorldModelProjector:
    def __init__(self, config: WorldModelProjectionConfig | None = None) -> None:
        self.config = config or WorldModelProjectionConfig()

    def project(
        self,
        *,
        task: TaskSpec,
        resources: ResourceSelection,
        scene: SceneSnapshot,
        capabilities: CapabilitySnapshot,
        query_facts: dict[str, Any] | None = None,
        known_failure_regions: list[dict[str, Any]] | None = None,
    ) -> TaskConditionedWorldModel:
        relevant_ids = _relevant_entity_ids(task.parameters)
        objects = [obj for obj in scene.objects if _entity_id(obj) in relevant_ids]
        if not relevant_ids and self.config.include_all_objects_when_unspecified:
            objects = list(scene.objects)
        objects = objects[: self.config.maximum_objects]

        regions = [region for region in scene.regions if _entity_id(region) in relevant_ids]
        robot_profile = next(
            (profile for profile in capabilities.robots if profile.get("id") == resources.robot.id),
            {},
        )
        return TaskConditionedWorldModel(
            task=task,
            resources=resources,
            scene_id=scene.scene_id,
            scene_revision=scene.scene_revision,
            bounds=scene.bounds,
            robot_profile=robot_profile,
            relevant_objects=objects,
            relevant_regions=regions,
            spawn_points=scene.spawn_points,
            query_facts=query_facts or {},
            known_failure_regions=known_failure_regions or [],
        )


def _relevant_entity_ids(parameters: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for name, value in parameters.items():
        if name.endswith("_id") and isinstance(value, str):
            ids.add(value)
        elif name.endswith("_ids") and isinstance(value, list):
            ids.update(item for item in value if isinstance(item, str))
    return ids


def _entity_id(entity: dict[str, Any]) -> str | None:
    value = entity.get("id") or entity.get("object_id") or entity.get("region_id")
    return value if isinstance(value, str) else None

