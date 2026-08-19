"""Immutable experiment protocol input models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field

from failure_client.contracts import (
    ContractModel,
    ResourceSelection,
    TaskSpec,
    VersionedContractModel,
)


class ExperimentMetadata(ContractModel):
    experiment_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    parent_experiment_id: str | None = None
    research_question: str = Field(min_length=1)
    hypothesis: str | None = None


class MethodConfig(ContractModel):
    plugin_id: str = Field(min_length=1)
    plugin_version: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class FailureDefinitionConfig(ContractModel):
    definition_id: str = Field(alias="id", min_length=1)
    version: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class ExperimentExecutionConfig(ContractModel):
    candidate_budget: int = Field(gt=0)
    repeats_per_candidate: int = Field(default=1, gt=0)
    master_seed: int = 0
    seed_policy: str = "sha256-v1"
    maximum_parallel_jobs: int = Field(default=1, gt=0)
    maximum_duration_s: float = Field(default=20.0, gt=0)


class ArtifactPolicy(ContractModel):
    trajectory: Literal["always", "never"] = "always"
    events: Literal["always", "never"] = "always"
    video: Literal["always", "never", "on_standard_event"] = "always"
    policy_trace: Literal["always", "never"] = "always"


class ExperimentProtocol(VersionedContractModel):
    experiment: ExperimentMetadata
    resources: ResourceSelection
    task: TaskSpec
    method: MethodConfig
    failure_definition: FailureDefinitionConfig
    execution: ExperimentExecutionConfig
    artifacts: ArtifactPolicy = Field(default_factory=ArtifactPolicy)

    @classmethod
    def load_yaml(cls, path: str | Path) -> ExperimentProtocol:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("experiment protocol must be a YAML object")
        return cls.model_validate(data)


def dump_protocol_yaml(protocol: ExperimentProtocol) -> str:
    data = protocol.model_dump(mode="json", by_alias=True, exclude_none=True)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=True)

