from __future__ import annotations

from failure_client.storage import ExperimentState

from .test_c6_orchestrator import make_orchestrator, make_protocol


def test_one_hundred_rollouts_complete_and_export_reproducible_failures(
    tmp_path,
    load_contract_fixture,
):
    orchestrator, repository, gateway = make_orchestrator(
        tmp_path,
        load_contract_fixture,
    )
    protocol = make_protocol(candidate_budget=100, repeats=1)

    summary = orchestrator.run(protocol)
    exported = orchestrator.export_experiment("exp_orchestrated")

    assert summary.state == ExperimentState.COMPLETED
    assert summary.candidate_count == 100
    assert summary.rollout_count == 100
    assert summary.evaluation_count == 100
    assert len(gateway.requests) == 100
    assert not [
        attempt
        for attempt in repository.list_rollout_attempts("exp_orchestrated")
        if attempt.error is not None
    ]
    assert exported.manifest_path.exists()
    assert exported.failure_case_count == summary.confirmed_failure_count


def test_sobol_method_runs_through_same_core_without_core_changes(
    tmp_path,
    load_contract_fixture,
):
    orchestrator, _, gateway = make_orchestrator(tmp_path, load_contract_fixture)
    random_protocol = make_protocol(candidate_budget=8, repeats=1)
    sobol_protocol = random_protocol.model_copy(
        update={
            "experiment": random_protocol.experiment.model_copy(
                update={
                    "experiment_id": "exp_sobol",
                    "title": "Sobol G1 obstacle risk search",
                }
            ),
            "method": random_protocol.method.model_copy(
                update={"plugin_id": "sobol_parametric"}
            ),
        }
    )

    summary = orchestrator.run(sobol_protocol)

    assert summary.state == ExperimentState.COMPLETED
    assert summary.candidate_count == 8
    assert summary.rollout_count == 8
    assert all(
        request.research_context.method_instance_id.startswith("sobol_parametric:")
        for request in gateway.requests.values()
    )
