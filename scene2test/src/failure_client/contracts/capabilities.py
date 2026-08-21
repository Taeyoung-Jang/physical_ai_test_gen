"""Capability negotiation contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, VersionedContractModel


class QueryCapability(ContractModel):
    query_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    parameter_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")


class OperationCapability(ContractModel):
    operation_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    phase: str | None = None
    parameter_schema: dict[str, Any] = Field(default_factory=dict, alias="schema")
    features: dict[str, Any] = Field(default_factory=dict)


class RecordingChannelCapability(ContractModel):
    channel_id: str = Field(min_length=1)
    version: str = "1.0"
    fields: list[str] = Field(default_factory=list)


class ArtifactFormatCapability(ContractModel):
    kind: str = Field(min_length=1)
    formats: list[str] = Field(default_factory=list)


class CapabilityLimits(ContractModel):
    maximum_episode_duration_s: float | None = Field(default=None, gt=0)
    maximum_interventions: int | None = Field(default=None, ge=0)
    maximum_upload_bytes: int | None = Field(default=None, ge=0)
    maximum_parallel_jobs: int | None = Field(default=None, ge=1)


class CapabilitySnapshot(VersionedContractModel):
    registry_revision: str = Field(min_length=1)
    contract_versions: list[str] = Field(default_factory=lambda: ["1.0"])
    scene_queries: list[QueryCapability] = Field(default_factory=list)
    intervention_operations: list[OperationCapability] = Field(default_factory=list)
    recording_channels: list[RecordingChannelCapability] = Field(default_factory=list)
    artifact_formats: list[ArtifactFormatCapability] = Field(default_factory=list)
    render_profiles: list[dict[str, Any]] = Field(default_factory=list)
    robots: list[dict[str, Any]] = Field(default_factory=list)
    controllers: list[dict[str, Any]] = Field(default_factory=list)
    policies: list[dict[str, Any]] = Field(default_factory=list)
    tasks: list[dict[str, Any]] = Field(default_factory=list)
    limits: CapabilityLimits = Field(default_factory=CapabilityLimits)

