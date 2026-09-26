"""Strict, opt-in measurement contracts; independent of legacy failure verdicts."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Family = Literal[
    "collision",
    "unreachable",
    "obstacle_interference",
    "goal_occupied",
    "human_safety_risk",
    "perception_error",
]
FAMILIES = (
    "collision",
    "unreachable",
    "obstacle_interference",
    "goal_occupied",
    "human_safety_risk",
    "perception_error",
)


class StrictRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class RunInput(StrictRecord):
    path: str = Field(min_length=1)
    method: Literal["afs", "random", "unassigned"] = "unassigned"
    seed: int = Field(default=0, ge=0)
    stage: Literal["discovery", "cold_start", "repeat", "boundary", "unknown"] = "unknown"


class ComparisonDesign(StrictRecord):
    """Declared design, not proof that an imported Random sampler was actually random."""

    domain_id: str = Field(min_length=1)
    sampling_distribution: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    valid_budget_per_seed: int = Field(gt=0)
    seeds: list[int] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_seeds(self):
        if any(s < 0 for s in self.seeds) or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be distinct nonnegative integers")
        return self


class MeasurementInput(StrictRecord):
    schema_version: Literal["failure-measurement-input-v1"] = "failure-measurement-input-v1"
    campaign_id: str = Field(min_length=1)
    design: ComparisonDesign | None = None
    runs: list[RunInput]


class Attribution(StrictRecord):
    """Produced by a trusted, tested detector; never read from an LLM proposal."""

    primary_family: Family
    rule_version: str = Field(min_length=1)
    evidence_refs: list[str] = Field(min_length=1)


class TraceMeasures(StrictRecord):
    state_samples: int = Field(ge=1)
    first_sample_s: float = Field(ge=0)
    last_sample_s: float = Field(ge=0)
    initial_goal_distance_m: float = Field(ge=0)
    minimum_goal_distance_m: float = Field(ge=0)
    last_sample_goal_distance_m: float = Field(ge=0)
    sampled_progress_m: float
    sampled_path_length_m: float = Field(ge=0)
    maximum_recorded_goal_dwell_s: float = Field(ge=0)
    minimum_base_height_m: float
    maximum_base_tilt_deg: float = Field(ge=0, le=180)
    action_counts: dict[str, int] = Field(default_factory=dict)
    event_counts: dict[str, int] | None = None


class EpisodeRecord(StrictRecord):
    schema_version: Literal["research-episode-v1"] = "research-episode-v1"
    source: RunInput
    evidence_id: str | None = None
    artifact_hashes: dict[str, str] = Field(default_factory=dict)
    status: Literal["VALID", "INCONCLUSIVE", "INCOMPLETE", "INVALID", "UNSUPPORTED"]
    exclusion_reason: str | None = None
    task_outcome: Literal["PASS", "FAIL", "INCONCLUSIVE"] = "INCONCLUSIVE"
    condition_id: str | None = None
    scene_id: str | None = None
    policy_origin: Literal["openai_api", "mock"] | None = None
    returned_models: list[str] = Field(default_factory=list)
    termination_reason: str | None = None
    measures: TraceMeasures | None = None
    attribution: Attribution | None = None
    simulation_s: float | None = Field(default=None, ge=0)
    robot_api_calls: int | None = Field(default=None, ge=0)
    observed_input_tokens: int | None = Field(default=None, ge=0)
    observed_output_tokens: int | None = Field(default=None, ge=0)
    calls_with_token_usage: int = Field(default=0, ge=0)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_outcome(self):
        if self.status == "VALID":
            if self.task_outcome not in {"PASS", "FAIL"} or self.exclusion_reason:
                raise ValueError("valid episode requires PASS/FAIL without exclusion")
            if not all((self.evidence_id, self.condition_id, self.scene_id, self.policy_origin)):
                raise ValueError("valid episode requires evidence and condition identities")
        elif not self.exclusion_reason or self.task_outcome != "INCONCLUSIVE":
            raise ValueError("excluded episode requires a reason and INCONCLUSIVE outcome")
        if self.attribution:
            if self.status != "VALID" or self.task_outcome != "FAIL":
                raise ValueError("failure attribution requires a valid goal FAIL")
            if not all(ref in self.artifact_hashes for ref in self.attribution.evidence_refs):
                raise ValueError("attribution requires verified artifact references")
        return self
