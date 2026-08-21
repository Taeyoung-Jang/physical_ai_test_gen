"""Append-only re-evaluation of stored raw rollout results."""

from __future__ import annotations

from pydantic import Field

from failure_client.archive import FailureArchive
from failure_client.contracts import ContractModel, canonical_sha256
from failure_client.evaluation import FailureDefinition, FailureEvaluator
from failure_client.storage import ClientRepository


class ReevaluationSummary(ContractModel):
    experiment_id: str
    definition_sha256: str
    evaluated_rollout_count: int = Field(ge=0)
    candidate_count: int = Field(ge=0)
    confirmed_failure_count: int = Field(ge=0)


class ReevaluationService:
    def __init__(self, repository: ClientRepository) -> None:
        self.repository = repository
        self.evaluator = FailureEvaluator()
        self.archive = FailureArchive(repository)

    def run(
        self,
        experiment_id: str,
        definition: FailureDefinition,
    ) -> ReevaluationSummary:
        self.repository.get_experiment(experiment_id)
        definition_sha = canonical_sha256(definition)
        candidate_ids: set[str] = set()
        evaluated = 0
        for attempt in self.repository.list_rollout_attempts(experiment_id):
            if attempt.result is None:
                continue
            evaluation = self.evaluator.evaluate(
                experiment_id=experiment_id,
                attempt_id=attempt.attempt_id,
                candidate_id=attempt.candidate_id,
                repeat_index=attempt.repeat_index,
                definition=definition,
                result=attempt.result,
            )
            self.repository.save_evaluation(evaluation)
            candidate_ids.add(attempt.candidate_id)
            evaluated += 1

        confirmed = 0
        for candidate_id in candidate_ids:
            record = self.archive.refresh(experiment_id, candidate_id, definition_sha)
            confirmed += record.confirmed_failure
        return ReevaluationSummary(
            experiment_id=experiment_id,
            definition_sha256=definition_sha,
            evaluated_rollout_count=evaluated,
            candidate_count=len(candidate_ids),
            confirmed_failure_count=confirmed,
        )
