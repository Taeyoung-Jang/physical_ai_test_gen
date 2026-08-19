"""Versioned failure definitions and immutable evaluation records."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from failure_client.contracts import ContractModel, VersionedContractModel


class EvaluationOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    INDETERMINATE = "INDETERMINATE"


class ValuePredicate(ContractModel):
    rule_id: str = Field(min_length=1)
    source: Literal["task_facts", "summary_metrics"]
    path: str = Field(min_length=1)
    operator: Literal[
        "eq",
        "ne",
        "lt",
        "lte",
        "gt",
        "gte",
        "truthy",
        "falsy",
        "exists",
    ]
    expected: Any = None

    @model_validator(mode="after")
    def require_expected_for_binary_operators(self) -> ValuePredicate:
        if self.operator in {"eq", "ne", "lt", "lte", "gt", "gte"} and self.expected is None:
            raise ValueError(f"operator {self.operator!r} requires expected")
        return self


class EventMeasurementPredicate(ContractModel):
    path: str = Field(min_length=1)
    operator: Literal["eq", "ne", "lt", "lte", "gt", "gte", "truthy", "falsy", "exists"]
    expected: Any = None

    @model_validator(mode="after")
    def require_expected_for_binary_operators(self) -> EventMeasurementPredicate:
        if self.operator in {"eq", "ne", "lt", "lte", "gt", "gte"} and self.expected is None:
            raise ValueError(f"operator {self.operator!r} requires expected")
        return self


class StandardEventRule(ContractModel):
    rule_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    minimum_count: int = Field(default=1, ge=1)
    after_timestamp_s: float = Field(default=0.0, ge=0)
    measurements: list[EventMeasurementPredicate] = Field(default_factory=list)


class FailureDefinition(VersionedContractModel):
    definition_id: str = Field(min_length=1)
    definition_version: str = Field(min_length=1)
    failure_predicates: list[ValuePredicate] = Field(default_factory=list)
    failure_events: list[StandardEventRule] = Field(default_factory=list)
    success_predicates: list[ValuePredicate] = Field(default_factory=list)
    failure_aggregation: Literal["any", "all"] = "any"
    success_aggregation: Literal["any", "all"] = "all"


class ResearchEvaluation(VersionedContractModel):
    evaluation_id: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    attempt_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    repeat_index: int = Field(ge=0)
    evaluator_id: str = Field(min_length=1)
    evaluator_version: str = Field(min_length=1)
    definition_id: str = Field(min_length=1)
    definition_version: str = Field(min_length=1)
    definition_sha256: str = Field(min_length=1)
    result_sha256: str = Field(min_length=1)
    outcome: EvaluationOutcome
    failure: bool | None = None
    matched_failure_rules: list[str] = Field(default_factory=list)
    unmet_success_rules: list[str] = Field(default_factory=list)
    diagnostic: str | None = None
    objectives: dict[str, float] = Field(default_factory=dict)
    created_at: datetime

    @model_validator(mode="after")
    def ensure_failure_matches_outcome(self) -> ResearchEvaluation:
        expected = {
            EvaluationOutcome.SUCCESS: False,
            EvaluationOutcome.FAILURE: True,
            EvaluationOutcome.INDETERMINATE: None,
        }[self.outcome]
        if self.failure is not expected:
            raise ValueError("failure must be false/true/null for success/failure/indeterminate")
        return self
