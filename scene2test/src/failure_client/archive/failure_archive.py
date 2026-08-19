"""Aggregate repeat evaluations while excluding invalid infrastructure runs."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from failure_client.evaluation import EvaluationOutcome, ResearchEvaluation
from failure_client.storage import ClientRepository

from .models import FailureCaseRecord


class FailureArchive:
    def __init__(
        self,
        repository: ClientRepository,
        *,
        minimum_failures: int = 1,
        confirmation_probability: float = 0.5,
    ) -> None:
        if minimum_failures < 1:
            raise ValueError("minimum_failures must be positive")
        if not 0 <= confirmation_probability <= 1:
            raise ValueError("confirmation_probability must be in [0, 1]")
        self.repository = repository
        self.minimum_failures = minimum_failures
        self.confirmation_probability = confirmation_probability

    def refresh(
        self,
        experiment_id: str,
        candidate_id: str,
        definition_sha256: str,
    ) -> FailureCaseRecord:
        evaluations = self.repository.list_evaluations(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            definition_sha256=definition_sha256,
        )
        record = self.aggregate(evaluations)
        self.repository.save_failure_case(record)
        return record

    def aggregate(self, evaluations: list[ResearchEvaluation]) -> FailureCaseRecord:
        if not evaluations:
            raise ValueError("at least one evaluation is required")
        identities = {
            (item.experiment_id, item.candidate_id, item.definition_sha256)
            for item in evaluations
        }
        if len(identities) != 1:
            raise ValueError("evaluations must belong to one candidate and failure definition")
        experiment_id, candidate_id, definition_sha256 = identities.pop()
        failure_count = sum(item.outcome == EvaluationOutcome.FAILURE for item in evaluations)
        success_count = sum(item.outcome == EvaluationOutcome.SUCCESS for item in evaluations)
        indeterminate_count = sum(
            item.outcome == EvaluationOutcome.INDETERMINATE for item in evaluations
        )
        valid_count = failure_count + success_count
        probability = failure_count / valid_count if valid_count else None
        confidence_interval = _wilson_interval(failure_count, valid_count)
        rules = sorted(
            {rule for item in evaluations for rule in item.matched_failure_rules}
        )
        objective_names = sorted(
            {name for item in evaluations for name in item.objectives}
        )
        minima = {
            name: min(item.objectives[name] for item in evaluations if name in item.objectives)
            for name in objective_names
        }
        maxima = {
            name: max(item.objectives[name] for item in evaluations if name in item.objectives)
            for name in objective_names
        }
        return FailureCaseRecord(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            definition_sha256=definition_sha256,
            valid_repeat_count=valid_count,
            failure_count=failure_count,
            success_count=success_count,
            indeterminate_count=indeterminate_count,
            failure_probability=probability,
            failure_probability_ci95=confidence_interval,
            confirmed_failure=(
                probability is not None
                and failure_count >= self.minimum_failures
                and probability >= self.confirmation_probability
            ),
            matched_failure_rules=rules,
            objective_minima=minima,
            objective_maxima=maxima,
            updated_at=datetime.now(UTC),
        )


def _wilson_interval(successes: int, trials: int) -> tuple[float, float] | None:
    if trials == 0:
        return None
    z = 1.959963984540054
    probability = successes / trials
    denominator = 1 + z**2 / trials
    centre = (probability + z**2 / (2 * trials)) / denominator
    radius = (
        z
        * math.sqrt(
            probability * (1 - probability) / trials
            + z**2 / (4 * trials**2)
        )
        / denominator
    )
    return max(0.0, centre - radius), min(1.0, centre + radius)
