"""Import legacy AFS mutation records without invoking its local PyBullet runner."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import Field

from failure_client.candidates import CandidateProposal
from failure_client.contracts import ContractModel
from failure_client.registry import MethodRequirements, VersionedRequirement

from ..base import CandidateObservation, MethodContext, MethodNotInitializedError, StopDecision


class LegacyAFSImportConfig(ContractModel):
    records: list[dict[str, Any]] = Field(min_length=1)
    operation: str = Field(min_length=1)
    operation_version: str = "1.0"
    coordinate_frame: str = "scene"
    static_parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_bindings: dict[str, str] = Field(default_factory=dict)


class LegacyAFSImportMethod:
    """Replay AFS-proposed mutations through the remote Client execution path."""

    plugin_id = "legacy_afs_import"
    plugin_version = "1.0.0"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = LegacyAFSImportConfig.model_validate(config)
        self.context: MethodContext | None = None
        self.index = 0

    def requirements(self) -> MethodRequirements:
        return MethodRequirements(
            intervention_operations=[
                VersionedRequirement(
                    capability_id=self.config.operation.rsplit(".", 1)[-1],
                    version=f"{self.config.operation_version.split('.', 1)[0]}.x",
                )
            ]
        )

    def initialize(self, context: MethodContext) -> None:
        self.context = context

    def propose(self, budget: int) -> list[CandidateProposal]:
        if self.context is None:
            raise MethodNotInitializedError(self.plugin_id)
        end = min(self.index + max(budget, 0), len(self.config.records))
        proposals = []
        for index in range(self.index, end):
            record = self.config.records[index]
            mutation = dict(record.get("mutation_params") or record.get("mutation") or {})
            parameters = copy.deepcopy(self.config.static_parameters)
            for name, value in mutation.items():
                _set_path(parameters, self.config.parameter_bindings.get(name, name), value)
            proposals.append(
                CandidateProposal(
                    candidate_id=f"legacy_afs_{index:08d}",
                    method_instance_id=self.context.method_instance_id,
                    intervention_intent={
                        "operation": self.config.operation,
                        "operation_version": self.config.operation_version,
                        "coordinate_frame": self.config.coordinate_frame,
                        "parameters": parameters,
                    },
                    tags=["legacy-afs-import"],
                )
            )
        self.index = end
        return proposals

    def observe(self, observations: list[CandidateObservation]) -> None:
        del observations

    def should_stop(self) -> StopDecision:
        stopped = self.index >= len(self.config.records)
        return StopDecision(
            should_stop=stopped,
            reason="legacy AFS import exhausted" if stopped else None,
        )

    def state_dict(self) -> dict[str, Any]:
        return {"state_schema_version": "1.0", "index": self.index}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if self.context is None:
            raise MethodNotInitializedError(self.plugin_id)
        if state.get("state_schema_version") != "1.0":
            raise ValueError("unsupported LegacyAFSImportMethod state schema")
        self.index = int(state["index"])


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    current = target
    parts = path.split(".")
    for part in parts[:-1]:
        child = current.setdefault(part, {})
        if not isinstance(child, dict):
            raise ValueError(f"parameter binding crosses a non-object at {part!r}")
        current = child
    current[parts[-1]] = value
