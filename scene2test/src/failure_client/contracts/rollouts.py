"""Asynchronous rollout request, status, and result contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from .artifacts import ArtifactRef
from .base import ContractModel, VersionedContractModel
from .interventions import InterventionSpec
from .resources import ResourceSelection


class RemoteJobState(StrEnum):
    QUEUED = "QUEUED"
    RESOLVING_RESOURCES = "RESOLVING_RESOURCES"
    VALIDATING_INTERVENTIONS = "VALIDATING_INTERVENTIONS"
    PREPARING_MODEL = "PREPARING_MODEL"
    INITIALIZING_RUNTIME = "INITIALIZING_RUNTIME"
    RUNNING = "RUNNING"
    FINALIZING_EVIDENCE = "FINALIZING_EVIDENCE"
    RENDERING = "RENDERING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class ResearchContext(ContractModel):
    experiment_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    method_instance_id: str = Field(min_length=1)
    opaque_tags: list[str] = Field(default_factory=list)


class TaskSpec(ContractModel):
    schema_id: str = Field(alias="schema", min_length=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExecutionSpec(ContractModel):
    seed: int
    physics_timestep_s: float | None = Field(default=None, gt=0)
    control_hz: float | None = Field(default=None, gt=0)
    maximum_duration_s: float = Field(gt=0)
    settling_duration_s: float | None = Field(default=None, ge=0)


class RecordingSpec(ContractModel):
    state_trajectory: bool = True
    action_trajectory: bool = True
    contact_events: bool = True
    policy_trace: bool = True
    camera_streams: list[str] = Field(default_factory=list)
    video: Literal["never", "always", "on_standard_event"] = "never"


class RolloutRequest(VersionedContractModel):
    client_request_id: str = Field(min_length=1)
    research_context: ResearchContext
    resources: ResourceSelection
    task: TaskSpec
    interventions: list[InterventionSpec] = Field(default_factory=list)
    execution: ExecutionSpec
    recording: RecordingSpec = Field(default_factory=RecordingSpec)


class RolloutAccepted(VersionedContractModel):
    job_id: str = Field(min_length=1)
    status: RemoteJobState
    request_sha256: str = Field(min_length=1)
    submitted_at: datetime


class RolloutJobStatus(VersionedContractModel):
    job_id: str = Field(min_length=1)
    status: RemoteJobState
    progress: dict[str, Any] = Field(default_factory=dict)
    updated_at: datetime | None = None


class ExecutionSummary(ContractModel):
    valid: bool
    status: RemoteJobState
    termination_reason: str | None = None
    determinism_level: str | None = None


class StandardEvent(ContractModel):
    event_type: str = Field(min_length=1)
    timestamp_s: float = Field(ge=0)
    measurements: dict[str, Any] = Field(default_factory=dict)


class RolloutResult(VersionedContractModel):
    job_id: str = Field(min_length=1)
    execution: ExecutionSummary
    task_facts: dict[str, Any] = Field(default_factory=dict)
    standard_events: list[StandardEvent] = Field(default_factory=list)
    summary_metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    reproduction: dict[str, Any] = Field(default_factory=dict)


class CancelResult(VersionedContractModel):
    job_id: str = Field(min_length=1)
    status: RemoteJobState
