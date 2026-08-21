"""Derived per-candidate failure archive records."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from failure_client.contracts import VersionedContractModel


class FailureCaseRecord(VersionedContractModel):
    experiment_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    definition_sha256: str = Field(min_length=1)
    valid_repeat_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    success_count: int = Field(ge=0)
    indeterminate_count: int = Field(ge=0)
    failure_probability: float | None = Field(default=None, ge=0, le=1)
    failure_probability_ci95: tuple[float, float] | None = None
    estimator: str = "empirical-wilson-95@1.0"
    confirmed_failure: bool
    matched_failure_rules: list[str] = Field(default_factory=list)
    objective_minima: dict[str, float] = Field(default_factory=dict)
    objective_maxima: dict[str, float] = Field(default_factory=dict)
    updated_at: datetime
