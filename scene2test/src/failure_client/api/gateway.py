"""Domain-facing port for the external RunPod simulation service."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from failure_client.contracts import (
    ArtifactRef,
    CancelResult,
    CapabilitySnapshot,
    LocalArtifact,
    RegistrySnapshot,
    ResourceRef,
    RolloutAccepted,
    RolloutJobStatus,
    RolloutRequest,
    RolloutResult,
    SceneQueryRequest,
    SceneQueryResult,
    SceneSnapshot,
)


@runtime_checkable
class SimulationGateway(Protocol):
    """Stable Client boundary; domain code must not depend on HTTP details."""

    def get_health(self) -> dict[str, Any]: ...

    def get_capabilities(self) -> CapabilitySnapshot: ...

    def get_registry_snapshot(self) -> RegistrySnapshot: ...

    def get_scene_snapshot(self, ref: ResourceRef) -> SceneSnapshot: ...

    def query_scene(self, request: SceneQueryRequest) -> SceneQueryResult: ...

    def submit_rollout(
        self,
        request: RolloutRequest,
        idempotency_key: str,
    ) -> RolloutAccepted: ...

    def get_rollout_status(self, job_id: str) -> RolloutJobStatus: ...

    def get_rollout_result(self, job_id: str) -> RolloutResult: ...

    def cancel_rollout(self, job_id: str) -> CancelResult: ...

    def download_artifact(self, ref: ArtifactRef) -> LocalArtifact: ...

