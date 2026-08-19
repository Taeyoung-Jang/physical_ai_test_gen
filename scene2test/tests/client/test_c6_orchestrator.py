from __future__ import annotations

import json

from failure_client.api import FakeSimulationGateway
from failure_client.contracts import (
    CapabilitySnapshot,
    ExecutionSummary,
    RegistrySnapshot,
    RemoteJobState,
    RolloutAccepted,
    RolloutRequest,
    RolloutResult,
    SceneSnapshot,
    StandardEvent,
)
from failure_client.experiments import ExperimentOrchestrator, ExperimentProtocol
from failure_client.storage import ClientRepository, ExperimentState


class AutoCompletingGateway(FakeSimulationGateway):
    def __init__(self, *args, fail_status_once: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.fail_status_once = fail_status_once

    def submit_rollout(
        self,
        request: RolloutRequest,
        idempotency_key: str,
    ) -> RolloutAccepted:
        accepted = super().submit_rollout(request, idempotency_key)
        if accepted.job_id not in self.results:
            risk = float(request.interventions[0].parameters["risk"])
            collision = risk >= 0.5
            self.complete_rollout(
                RolloutResult(
                    job_id=accepted.job_id,
                    execution=ExecutionSummary(
                        valid=True,
                        status=RemoteJobState.SUCCEEDED,
                    ),
                    task_facts={"task": {"success": True}},
                    standard_events=(
                        [StandardEvent(event_type="collision", timestamp_s=1.0)]
                        if collision
                        else []
                    ),
                    summary_metrics={"risk": risk},
                )
            )
        return accepted

    def get_rollout_status(self, job_id: str):
        if self.fail_status_once:
            self.fail_status_once = False
            raise RuntimeError("simulated Client process interruption")
        return super().get_rollout_status(job_id)


def make_protocol(candidate_budget: int = 4, repeats: int = 2) -> ExperimentProtocol:
    return ExperimentProtocol.model_validate(
        {
            "experiment": {
                "experiment_id": "exp_orchestrated",
                "title": "G1 obstacle risk search",
                "research_question": "Which primitive placements trigger collision events?",
            },
            "resources": {
                "scene": {"id": "scene_001", "revision": "sha256:scene-v1"},
                "robot": {
                    "id": "unitree_g1",
                    "profile_id": "default",
                    "revision": "sha256:robot-v1",
                },
                "controller": {
                    "id": "groot_locomotion",
                    "revision": "sha256:controller-v1",
                },
                "policy": {
                    "id": "scripted_navigation",
                    "revision": "sha256:policy-v1",
                },
            },
            "task": {"schema": "navigate_to_pose@1.0", "parameters": {}},
            "method": {
                "plugin_id": "random_parametric",
                "plugin_version": "1.0.0",
                "config": {
                    "operation": "add_primitive",
                    "parameter_space": {
                        "risk": {"kind": "continuous", "low": 0.0, "high": 1.0}
                    },
                    "static_parameters": {"shape": "box"},
                    "maximum_candidates": candidate_budget,
                },
            },
            "failure_definition": {
                "id": "collision_failure",
                "version": "1.0",
                "config": {
                    "failure_events": [
                        {"rule_id": "collision", "event_type": "collision"}
                    ]
                },
            },
            "execution": {
                "candidate_budget": candidate_budget,
                "repeats_per_candidate": repeats,
                "master_seed": 7,
                "maximum_parallel_jobs": 2,
                "maximum_duration_s": 10.0,
            },
            "artifacts": {"video": "never"},
        }
    )


def make_orchestrator(tmp_path, load_contract_fixture, *, fail_status_once=False):
    capabilities = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    registry = RegistrySnapshot.model_validate(load_contract_fixture("registry_v1.json"))
    scene = SceneSnapshot.model_validate(load_contract_fixture("scene_snapshot_v1.json"))
    gateway = AutoCompletingGateway(
        capabilities=capabilities,
        registry=registry,
        artifact_dir=tmp_path / "artifacts",
        scene_snapshots={(scene.scene_id, scene.scene_revision): scene},
        fail_status_once=fail_status_once,
    )
    repository = ClientRepository(tmp_path / "client.sqlite")
    orchestrator = ExperimentOrchestrator(
        repository,
        gateway,
        workspace_dir=tmp_path,
        poll_interval_s=0,
        sleep=lambda _: None,
    )
    return orchestrator, repository, gateway


def test_end_to_end_experiment_runs_repeats_and_is_safe_to_resume(
    tmp_path,
    load_contract_fixture,
):
    orchestrator, repository, gateway = make_orchestrator(
        tmp_path,
        load_contract_fixture,
    )
    protocol = make_protocol()

    summary = orchestrator.run(protocol)
    replayed = orchestrator.run(protocol, resume=True)

    assert summary.state == ExperimentState.COMPLETED
    assert summary.candidate_count == 4
    assert summary.observed_candidate_count == 4
    assert summary.rollout_count == 8
    assert summary.evaluation_count == 8
    assert replayed == summary
    assert len(gateway.requests) == 8
    assert len(repository.list_candidates("exp_orchestrated")) == 4
    exports = list(
        (tmp_path / "experiments" / "exp_orchestrated" / "exports").glob("*.json")
    )
    assert len(exports) == 1
    manifest = json.loads(exports[0].read_text(encoding="utf-8"))
    assert len(manifest["failure_cases"]) == summary.confirmed_failure_count
    assert "protocol_lock" in manifest


def test_interrupted_run_resumes_without_duplicate_remote_rollout(
    tmp_path,
    load_contract_fixture,
):
    orchestrator, repository, gateway = make_orchestrator(
        tmp_path,
        load_contract_fixture,
        fail_status_once=True,
    )
    protocol = make_protocol(candidate_budget=3, repeats=1)

    try:
        orchestrator.run(protocol)
    except RuntimeError as exc:
        assert "simulated Client process interruption" in str(exc)
    else:
        raise AssertionError("the interruption must escape the run")

    assert repository.get_experiment("exp_orchestrated")["state"] == ExperimentState.PAUSED
    result = orchestrator.run(protocol, resume=True)

    assert result.state == ExperimentState.COMPLETED
    assert result.candidate_count == 3
    assert result.rollout_count == 3
    assert len(gateway.requests) == 3


def test_branch_experiment_records_parent_provenance(tmp_path, load_contract_fixture):
    orchestrator, repository, _ = make_orchestrator(tmp_path, load_contract_fixture)
    parent = make_protocol(candidate_budget=1, repeats=1)
    orchestrator.run(parent)
    child = parent.model_copy(
        update={
            "experiment": parent.experiment.model_copy(
                update={
                    "experiment_id": "exp_branch",
                    "parent_experiment_id": "exp_orchestrated",
                    "title": "Branched G1 obstacle risk search",
                }
            )
        }
    )

    result = orchestrator.run(child)

    assert result.state == ExperimentState.COMPLETED
    assert repository.get_experiment("exp_branch")["parent_experiment_id"] == (
        "exp_orchestrated"
    )
