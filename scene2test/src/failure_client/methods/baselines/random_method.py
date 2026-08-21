"""Deterministic checkpointable random/domain-randomization baseline."""

from __future__ import annotations

from typing import Any

import numpy as np

from failure_client.candidates import CandidateProposal
from failure_client.registry import MethodRequirements, VersionedRequirement

from ..base import (
    CandidateObservation,
    MethodContext,
    MethodNotInitializedError,
    StopDecision,
)
from ..parameters import ParametricMethodConfig, render_parameters, sample_with_rng


class RandomMethod:
    plugin_id = "random_parametric"
    plugin_version = "1.0.0"

    def __init__(self, config: dict[str, Any]) -> None:
        self.config = ParametricMethodConfig.model_validate(config)
        self.context: MethodContext | None = None
        self.rng: np.random.Generator | None = None
        self.sequence = 0
        self.observation_count = 0
        self.failure_count = 0

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
        self.rng = np.random.default_rng(context.master_seed)

    def propose(self, budget: int) -> list[CandidateProposal]:
        if self.context is None or self.rng is None:
            raise MethodNotInitializedError(self.plugin_id)
        remaining = self._remaining()
        count = min(max(budget, 0), remaining) if remaining is not None else max(budget, 0)
        proposals: list[CandidateProposal] = []
        for _ in range(count):
            sampled = {
                name: sample_with_rng(spec, self.rng)
                for name, spec in sorted(self.config.parameter_space.items())
            }
            candidate_id = f"random_{self.sequence:08d}"
            self.sequence += 1
            proposals.append(
                CandidateProposal(
                    candidate_id=candidate_id,
                    method_instance_id=self.context.method_instance_id,
                    intervention_intent={
                        "operation": self.config.operation,
                        "operation_version": self.config.operation_version,
                        "coordinate_frame": self.config.coordinate_frame,
                        "parameters": render_parameters(self.config, sampled),
                    },
                    tags=self.config.tags,
                )
            )
        return proposals

    def observe(self, observations: list[CandidateObservation]) -> None:
        self.observation_count += len(observations)
        self.failure_count += sum(item.failure is True for item in observations)

    def should_stop(self) -> StopDecision:
        remaining = self._remaining()
        return StopDecision(
            should_stop=remaining == 0,
            reason="maximum_candidates reached" if remaining == 0 else None,
        )

    def state_dict(self) -> dict[str, Any]:
        if self.rng is None:
            raise MethodNotInitializedError(self.plugin_id)
        return {
            "state_schema_version": "1.0",
            "sequence": self.sequence,
            "observation_count": self.observation_count,
            "failure_count": self.failure_count,
            "rng_state": self.rng.bit_generator.state,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        if self.rng is None:
            raise MethodNotInitializedError(self.plugin_id)
        if state.get("state_schema_version") != "1.0":
            raise ValueError("unsupported RandomMethod state schema")
        self.sequence = int(state["sequence"])
        self.observation_count = int(state["observation_count"])
        self.failure_count = int(state["failure_count"])
        self.rng.bit_generator.state = state["rng_state"]

    def _remaining(self) -> int | None:
        if self.config.maximum_candidates is None:
            return None
        return max(self.config.maximum_candidates - self.sequence, 0)

