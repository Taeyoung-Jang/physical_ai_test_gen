"""Revision-preserving synchronization of the external Server registry."""

from __future__ import annotations

from pydantic import Field

from failure_client.api import SimulationGateway
from failure_client.contracts import (
    CapabilitySnapshot,
    ContractModel,
    RegistrySnapshot,
    ResourceRef,
    SceneQueryRequest,
    SceneQueryResult,
    SceneSnapshot,
)
from failure_client.storage import ClientRepository


class RegistrySyncResult(ContractModel):
    registry_revision: str
    scene_count: int = Field(ge=0)
    robot_count: int = Field(ge=0)
    controller_count: int = Field(ge=0)
    policy_count: int = Field(ge=0)
    task_count: int = Field(ge=0)


class RegistrySynchronizer:
    def __init__(self, repository: ClientRepository, gateway: SimulationGateway) -> None:
        self.repository = repository
        self.gateway = gateway

    def sync(self, *, max_consistency_attempts: int = 3) -> RegistrySyncResult:
        if max_consistency_attempts < 1:
            raise ValueError("max_consistency_attempts must be at least 1")
        capabilities: CapabilitySnapshot | None = None
        registry: RegistrySnapshot | None = None
        for _ in range(max_consistency_attempts):
            capabilities = self.gateway.get_capabilities()
            registry = self.gateway.get_registry_snapshot()
            if capabilities.registry_revision == registry.registry_revision:
                break
        else:
            raise RuntimeError("Server registry changed repeatedly during synchronization")
        if capabilities is None or registry is None:
            raise AssertionError("registry synchronization did not fetch snapshots")
        self.repository.store_registry_snapshot(capabilities, registry)
        return RegistrySyncResult(
            registry_revision=registry.registry_revision,
            scene_count=len(registry.scenes),
            robot_count=len(registry.robots),
            controller_count=len(registry.controllers),
            policy_count=len(registry.policies),
            task_count=len(registry.tasks),
        )

    def require_scene_snapshot(self, ref: ResourceRef) -> SceneSnapshot:
        try:
            return self.repository.get_scene_snapshot(ref.id, ref.revision)
        except KeyError:
            snapshot = self.gateway.get_scene_snapshot(ref)
            self.repository.store_scene_snapshot(snapshot)
            return snapshot

    def query_scene(
        self,
        request: SceneQueryRequest,
        *,
        use_cache: bool = True,
    ) -> SceneQueryResult:
        if use_cache:
            try:
                return self.repository.get_scene_query_result(request)
            except KeyError:
                pass
        result = self.gateway.query_scene(request)
        self.repository.store_scene_query_result(request, result)
        return result

