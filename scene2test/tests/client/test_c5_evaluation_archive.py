from __future__ import annotations

from failure_client.archive import FailureArchive
from failure_client.contracts import (
    ExecutionSummary,
    RemoteJobState,
    RolloutResult,
    StandardEvent,
    canonical_sha256,
)
from failure_client.evaluation import (
    EvaluationOutcome,
    EventMeasurementPredicate,
    FailureDefinition,
    FailureEvaluator,
    StandardEventRule,
    ValuePredicate,
)
from failure_client.experiments import ReevaluationService
from failure_client.storage import ClientRepository

from .test_contracts import make_rollout_request


def make_repository(tmp_path) -> ClientRepository:
    repository = ClientRepository(tmp_path / "evaluation.sqlite")
    repository.create_experiment("exp_001", {"name": "test"}, {"locked": True})
    return repository


def make_result(
    job_id: str,
    *,
    success: bool = True,
    collision: bool = False,
    valid: bool = True,
) -> RolloutResult:
    events = (
        [StandardEvent(event_type="collision", timestamp_s=0.5, measurements={"force": 8.0})]
        if collision
        else []
    )
    return RolloutResult(
        job_id=job_id,
        execution=ExecutionSummary(
            valid=valid,
            status=RemoteJobState.SUCCEEDED if valid else RemoteJobState.FAILED,
            termination_reason=None if valid else "runtime initialization failed",
        ),
        task_facts={"task": {"success": success}},
        standard_events=events,
        summary_metrics={"minimum_clearance_m": 0.03},
    )


def make_definition(version: str = "1.0") -> FailureDefinition:
    return FailureDefinition(
        definition_id="navigation_safety",
        definition_version=version,
        failure_events=[StandardEventRule(rule_id="collision", event_type="collision")],
        success_predicates=[
            ValuePredicate(
                rule_id="task_completed",
                source="task_facts",
                path="task.success",
                operator="truthy",
            )
        ],
    )


def test_event_rules_can_filter_server_measurements():
    evaluator = FailureEvaluator()
    definition = FailureDefinition(
        definition_id="severe_collision",
        definition_version="1.0",
        failure_events=[
            StandardEventRule(
                rule_id="high_force_collision",
                event_type="collision",
                measurements=[
                    EventMeasurementPredicate(
                        path="force",
                        operator="gte",
                        expected=10.0,
                    )
                ],
            )
        ],
    )
    low_force = make_result("job_low", collision=True).model_copy(
        update={
            "standard_events": [
                StandardEvent(
                    event_type="collision",
                    timestamp_s=0.5,
                    measurements={"force": 8.0},
                )
            ]
        }
    )

    evaluation = evaluator.evaluate(
        experiment_id="exp_001",
        attempt_id="attempt_low",
        candidate_id="cand_001",
        repeat_index=0,
        definition=definition,
        result=low_force,
    )

    assert evaluation.outcome == EvaluationOutcome.SUCCESS


def create_attempt(repository: ClientRepository, repeat_index: int):
    request = make_rollout_request().model_copy(
        update={
            "client_request_id": f"request_{repeat_index}",
            "execution": make_rollout_request().execution.model_copy(
                update={"seed": 100 + repeat_index}
            ),
        }
    )
    return repository.create_rollout_attempt(
        experiment_id="exp_001",
        candidate_id="cand_001",
        repeat_index=repeat_index,
        request=request,
    )


def test_execution_error_is_indeterminate_not_research_failure(tmp_path):
    evaluator = FailureEvaluator()
    result = make_result("job_invalid", valid=False)

    evaluation = evaluator.evaluate(
        experiment_id="exp_001",
        attempt_id="attempt_invalid",
        candidate_id="cand_001",
        repeat_index=0,
        definition=make_definition(),
        result=result,
    )

    assert evaluation.outcome == EvaluationOutcome.INDETERMINATE
    assert evaluation.failure is None
    assert "runtime initialization" in (evaluation.diagnostic or "")


def test_same_result_can_be_re_evaluated_under_versioned_definitions(tmp_path):
    repository = make_repository(tmp_path)
    attempt = create_attempt(repository, 0)
    result = make_result("job_001", success=False)
    evaluator = FailureEvaluator()
    strict = make_definition("1.0")
    permissive = FailureDefinition(
        definition_id="navigation_safety",
        definition_version="2.0",
    )

    first = repository.save_evaluation(
        evaluator.evaluate(
            experiment_id="exp_001",
            attempt_id=attempt.attempt_id,
            candidate_id="cand_001",
            repeat_index=0,
            definition=strict,
            result=result,
        )
    )
    second = repository.save_evaluation(
        evaluator.evaluate(
            experiment_id="exp_001",
            attempt_id=attempt.attempt_id,
            candidate_id="cand_001",
            repeat_index=0,
            definition=permissive,
            result=result,
        )
    )

    assert first.outcome == EvaluationOutcome.FAILURE
    assert second.outcome == EvaluationOutcome.SUCCESS
    assert first.evaluation_id != second.evaluation_id
    assert len(repository.list_evaluations(experiment_id="exp_001")) == 2


def test_reevaluation_service_uses_stored_raw_result_without_new_rollout(tmp_path):
    repository = make_repository(tmp_path)
    attempt = create_attempt(repository, 0)
    repository.save_result(attempt.attempt_id, make_result("job_stored", success=False))
    service = ReevaluationService(repository)

    first = service.run("exp_001", make_definition("1.0"))
    second = service.run(
        "exp_001",
        FailureDefinition(
            definition_id="navigation_safety",
            definition_version="2.0",
        ),
    )

    assert first.evaluated_rollout_count == 1
    assert first.confirmed_failure_count == 1
    assert second.confirmed_failure_count == 0
    assert len(repository.list_rollout_attempts("exp_001")) == 1
    assert len(repository.list_evaluations(experiment_id="exp_001")) == 2


def test_evaluation_replay_is_append_only_and_idempotent(tmp_path):
    repository = make_repository(tmp_path)
    attempt = create_attempt(repository, 0)
    evaluator = FailureEvaluator()
    arguments = {
        "experiment_id": "exp_001",
        "attempt_id": attempt.attempt_id,
        "candidate_id": "cand_001",
        "repeat_index": 0,
        "definition": make_definition(),
        "result": make_result("job_001", collision=True),
    }

    first = repository.save_evaluation(evaluator.evaluate(**arguments))
    replayed = repository.save_evaluation(evaluator.evaluate(**arguments))

    assert replayed == first
    assert len(repository.list_evaluations(experiment_id="exp_001")) == 1


def test_archive_excludes_indeterminate_repeats_from_failure_probability(tmp_path):
    repository = make_repository(tmp_path)
    evaluator = FailureEvaluator()
    definition = make_definition()
    results = [
        make_result("job_0", collision=True),
        make_result("job_1", success=False),
        make_result("job_2", success=True),
        make_result("job_3", valid=False),
    ]
    for repeat_index, result in enumerate(results):
        attempt = create_attempt(repository, repeat_index)
        evaluation = evaluator.evaluate(
            experiment_id="exp_001",
            attempt_id=attempt.attempt_id,
            candidate_id="cand_001",
            repeat_index=repeat_index,
            definition=definition,
            result=result,
        )
        repository.save_evaluation(evaluation)

    archive = FailureArchive(
        repository,
        minimum_failures=2,
        confirmation_probability=0.6,
    )
    record = archive.refresh("exp_001", "cand_001", canonical_sha256(definition))

    assert record.failure_count == 2
    assert record.success_count == 1
    assert record.indeterminate_count == 1
    assert record.valid_repeat_count == 3
    assert record.failure_probability == 2 / 3
    assert record.failure_probability_ci95 is not None
    assert record.failure_probability_ci95[0] < record.failure_probability
    assert record.failure_probability_ci95[1] > record.failure_probability
    assert record.confirmed_failure is True
    assert repository.get_failure_case(
        "exp_001", "cand_001", canonical_sha256(definition)
    ) == record
