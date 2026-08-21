"""Deterministic researcher-specified candidate baseline."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from failure_client.candidates import CandidateProposal
from failure_client.contracts import ContractModel
from failure_client.registry import MethodRequirements, VersionedRequirement

from ..base import CandidateObservation, MethodContext, MethodNotInitializedError, StopDecision


class ManualMethodConfig(ContractModel):
    candidates: list[dict[str, Any]] = Field(min_length=1)


class ManualMethod:
    plugin_id = "manual"
    plugin_version = "1.0.0"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = ManualMethodConfig.model_validate(config)
        self.context: MethodContext | None = None
        self.index = 0

    def requirements(self) -> MethodRequirements:
        operation_ids = {
            str(item.get("operation") or item.get("kind") or "").rsplit(".", 1)[-1]
            for item in self.config.candidates
        }
        return MethodRequirements(
            intervention_operations=[
                VersionedRequirement(capability_id=item)
                for item in sorted(operation_ids)
                if item
            ]
        )

    def initialize(self, context: MethodContext) -> None:
        self.context = context

    def propose(self, budget: int) -> list[CandidateProposal]:
        if self.context is None:
            raise MethodNotInitializedError(self.plugin_id)
        end = min(self.index + max(budget, 0), len(self.config.candidates))
        proposals = [
            CandidateProposal(
                candidate_id=f"manual_{index:08d}",
                method_instance_id=self.context.method_instance_id,
                intervention_intent=self.config.candidates[index],
                tags=["manual"],
            )
            for index in range(self.index, end)
        ]
        self.index = end
        return proposals

    def observe(self, observations: list[CandidateObservation]) -> None:
        del observations

    def should_stop(self) -> StopDecision:
        stopped = self.index >= len(self.config.candidates)
        return StopDecision(
            should_stop=stopped,
            reason="manual candidate list exhausted" if stopped else None,
        )

    def state_dict(self) -> dict[str, Any]:
        return {"state_schema_version": "1.0", "index": self.index}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if self.context is None:
            raise MethodNotInitializedError(self.plugin_id)
        if state.get("state_schema_version") != "1.0":
            raise ValueError("unsupported ManualMethod state schema")
        self.index = int(state["index"])

