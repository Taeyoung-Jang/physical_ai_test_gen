"""In-memory simulation gateway for Client and method tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from failure_client.contracts import (
    ArtifactRef,
    CancelResult,
    CapabilitySnapshot,
    ErrorInfo,
    GatewayHTTPError,
    LocalArtifact,
    RegistrySnapshot,
    RemoteJobState,
    ResourceRef,
    RolloutAccepted,
    RolloutJobStatus,
    RolloutRequest,
    RolloutResult,
    SceneQueryRequest,
    SceneQueryResult,
    SceneSnapshot,
    canonical_sha256,
)

from .artifact_downloader import persist_verified_artifact
from .gateway import SimulationGateway


class FakeSimulationGateway(SimulationGateway):
    """Deterministic gateway with explicit hooks for remote state transitions."""

    def __init__(
        self,
        *,
        capabilities: CapabilitySnapshot,
        registry: RegistrySnapshot,
        artifact_dir: Path,
        scene_snapshots: dict[tuple[str, str], SceneSnapshot] | None = None,
        query_results: dict[tuple[str, str, str], SceneQueryResult] | None = None,
        artifact_payloads: dict[str, bytes] | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.registry = registry
        self.artifact_dir = artifact_dir
        self.scene_snapshots = scene_snapshots or {}
        self.query_results = query_results or {}
        self.artifact_payloads = artifact_payloads or {}
        self.requests: dict[str, RolloutRequest] = {}
        self.statuses: dict[str, RolloutJobStatus] = {}
        self.results: dict[str, RolloutResult] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._next_job_number = 1

    def get_health(self) -> dict[str, Any]:
        return {"status": "ok", "fake": True}

    def get_capabilities(self) -> CapabilitySnapshot:
        return self.capabilities

    def get_registry_snapshot(self) -> RegistrySnapshot:
        return self.registry

    def get_scene_snapshot(self, ref: ResourceRef) -> SceneSnapshot:
        try:
            return self.scene_snapshots[(ref.id, ref.revision)]
        except KeyError as exc:
            error = self._not_found(
                "RESOURCE_REVISION_NOT_FOUND",
                f"scene {ref.id}@{ref.revision}",
            )
            raise error from exc

    def query_scene(self, request: SceneQueryRequest) -> SceneQueryResult:
        key = (request.scene.id, request.scene.revision, request.query_id)
        try:
            return self.query_results[key]
        except KeyError as exc:
            raise self._not_found("QUERY_FIXTURE_NOT_FOUND", repr(key)) from exc

    def submit_rollout(
        self,
        request: RolloutRequest,
        idempotency_key: str,
    ) -> RolloutAccepted:
        request_hash = canonical_sha256(request)
        existing = self._idempotency.get(idempotency_key)
        if existing is not None:
            existing_hash, job_id = existing
            if existing_hash != request_hash:
                raise GatewayHTTPError(
                    409,
                    ErrorInfo(
                        code="IDEMPOTENCY_CONFLICT",
                        message="idempotency key was already used for another request",
                    ),
                )
            return RolloutAccepted(
                job_id=job_id,
                status=self.statuses[job_id].status,
                request_sha256=request_hash,
                submitted_at=datetime.now(UTC),
            )

        job_id = f"fake_job_{self._next_job_number:05d}"
        self._next_job_number += 1
        self._idempotency[idempotency_key] = (request_hash, job_id)
        self.requests[job_id] = request
        self.statuses[job_id] = RolloutJobStatus(job_id=job_id, status=RemoteJobState.QUEUED)
        return RolloutAccepted(
            job_id=job_id,
            status=RemoteJobState.QUEUED,
            request_sha256=request_hash,
            submitted_at=datetime.now(UTC),
        )

    def get_rollout_status(self, job_id: str) -> RolloutJobStatus:
        try:
            return self.statuses[job_id]
        except KeyError as exc:
            raise self._not_found("JOB_NOT_FOUND", job_id) from exc

    def get_rollout_result(self, job_id: str) -> RolloutResult:
        try:
            return self.results[job_id]
        except KeyError as exc:
            if job_id not in self.statuses:
                raise self._not_found("JOB_NOT_FOUND", job_id) from exc
            raise GatewayHTTPError(
                409,
                ErrorInfo(code="RESULT_NOT_READY", message=f"result for {job_id} is not ready"),
            ) from exc

    def cancel_rollout(self, job_id: str) -> CancelResult:
        if job_id not in self.statuses:
            raise self._not_found("JOB_NOT_FOUND", job_id)
        self.statuses[job_id] = RolloutJobStatus(
            job_id=job_id,
            status=RemoteJobState.CANCELLED,
        )
        return CancelResult(job_id=job_id, status=RemoteJobState.CANCELLED)

    def download_artifact(self, ref: ArtifactRef) -> LocalArtifact:
        try:
            payload = self.artifact_payloads[ref.artifact_id]
        except KeyError as exc:
            raise self._not_found("ARTIFACT_NOT_FOUND", ref.artifact_id) from exc
        return persist_verified_artifact(ref, payload, self.artifact_dir)

    def set_job_status(self, job_id: str, status: RemoteJobState) -> None:
        if job_id not in self.statuses:
            raise self._not_found("JOB_NOT_FOUND", job_id)
        self.statuses[job_id] = RolloutJobStatus(job_id=job_id, status=status)

    def complete_rollout(self, result: RolloutResult) -> None:
        if result.job_id not in self.statuses:
            raise self._not_found("JOB_NOT_FOUND", result.job_id)
        self.results[result.job_id] = result
        self.statuses[result.job_id] = RolloutJobStatus(
            job_id=result.job_id,
            status=RemoteJobState.SUCCEEDED,
        )

    @staticmethod
    def _not_found(code: str, subject: str) -> GatewayHTTPError:
        return GatewayHTTPError(404, ErrorInfo(code=code, message=f"not found: {subject}"))
