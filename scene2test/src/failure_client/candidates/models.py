"""Research-level candidate proposal and built intervention models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from failure_client.contracts import ContractModel, InterventionSpec


class CandidateHypothesis(ContractModel):
    mechanism: str = ""
    target_entities: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)


class CandidateProposal(ContractModel):
    candidate_id: str = Field(min_length=1)
    method_instance_id: str = Field(min_length=1)
    hypothesis: CandidateHypothesis = Field(default_factory=CandidateHypothesis)
    intervention_intent: dict[str, Any]
    parent_candidate_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class BuiltCandidate(ContractModel):
    proposal: CandidateProposal
    interventions: list[InterventionSpec]
    canonical_sha256: str = Field(min_length=1)


class CandidateIssue(ContractModel):
    severity: Literal["ERROR", "WARNING"]
    code: str
    message: str
    operation_id: str | None = None


class CandidateValidationResult(ContractModel):
    valid: bool
    issues: list[CandidateIssue] = Field(default_factory=list)

