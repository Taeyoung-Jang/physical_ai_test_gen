"""Import LAM-guided FailureCaseCandidate dictionaries as remote interventions."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from failure_client.candidates import CandidateHypothesis, CandidateProposal
from failure_client.contracts import ContractModel
from failure_client.registry import MethodRequirements, VersionedRequirement

from ..base import CandidateObservation, MethodContext, MethodNotInitializedError, StopDecision


class LegacyLAMImportConfig(ContractModel):
    cases: list[dict[str, Any]] = Field(min_length=1)
    operation: str = "add_mesh"
    operation_version: str = "1.0"
    coordinate_frame: str = "scene"


class LegacyLAMGuidedImportMethod:
    """Replay generated LAM cases while leaving legacy policy/oracle code untouched."""

    plugin_id = "legacy_lam_guided_import"
    plugin_version = "1.0.0"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = LegacyLAMImportConfig.model_validate(config)
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
        end = min(self.index + max(budget, 0), len(self.config.cases))
        proposals = []
        for index in range(self.index, end):
            case = self.config.cases[index]
            operations = [
                {
                    "operation_id": f"insert_{item_index:03d}",
                    "operation": self.config.operation,
                    "operation_version": self.config.operation_version,
                    "coordinate_frame": self.config.coordinate_frame,
                    "parameters": {
                        "asset_id": spec.get("asset_id"),
                        "object_id": spec.get("obj_id"),
                        "position_m": spec.get("position"),
                    },
                }
                for item_index, spec in enumerate(case.get("insert_specs") or [])
            ]
            if not operations:
                raise ValueError(f"LAM case at index {index} has no insert_specs")
            proposals.append(
                CandidateProposal(
                    candidate_id=f"legacy_lam_{index:08d}",
                    method_instance_id=self.context.method_instance_id,
                    hypothesis=CandidateHypothesis(
                        mechanism=str(case.get("expected_failure") or case.get("family") or ""),
                    ),
                    intervention_intent={"operations": operations},
                    tags=["legacy-lam-guided-import", str(case.get("family") or "unknown")],
                )
            )
        self.index = end
        return proposals

    def observe(self, observations: list[CandidateObservation]) -> None:
        del observations

    def should_stop(self) -> StopDecision:
        stopped = self.index >= len(self.config.cases)
        return StopDecision(
            should_stop=stopped,
            reason="legacy LAM-guided import exhausted" if stopped else None,
        )

    def state_dict(self) -> dict[str, Any]:
        return {"state_schema_version": "1.0", "index": self.index}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if self.context is None:
            raise MethodNotInitializedError(self.plugin_id)
        if state.get("state_schema_version") != "1.0":
            raise ValueError("unsupported LegacyLAMGuidedImportMethod state schema")
        self.index = int(state["index"])
