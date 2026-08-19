"""Stable failure-discovery method contract."""

from __future__ import annotations

from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import Field

from failure_client.candidates import CandidateProposal
from failure_client.contracts import CapabilitySnapshot, ContractModel
from failure_client.registry import MethodRequirements
from failure_client.world_model import TaskConditionedWorldModel


class MethodContext(ContractModel):
    experiment_id: str
    method_instance_id: str
    master_seed: int
    world_model: TaskConditionedWorldModel
    capabilities: CapabilitySnapshot


class CandidateObservation(ContractModel):
    candidate_id: str
    status: Literal[
        "EVALUATED",
        "VALIDATION_REJECTED",
        "INDETERMINATE",
        "EXECUTION_ERROR",
    ]
    failure: bool | None = None
    objectives: dict[str, float] = Field(default_factory=dict)
    details: dict[str, Any] = Field(default_factory=dict)


class StopDecision(ContractModel):
    should_stop: bool
    reason: str | None = None


@runtime_checkable
class FailureDiscoveryMethod(Protocol):
    plugin_id: str
    plugin_version: str

    def requirements(self) -> MethodRequirements: ...

    def initialize(self, context: MethodContext) -> None: ...

    def propose(self, budget: int) -> list[CandidateProposal]: ...

    def observe(self, observations: list[CandidateObservation]) -> None: ...

    def should_stop(self) -> StopDecision: ...

    def state_dict(self) -> dict[str, Any]: ...

    def load_state_dict(self, state: dict[str, Any]) -> None: ...


class MethodNotInitializedError(RuntimeError):
    pass

