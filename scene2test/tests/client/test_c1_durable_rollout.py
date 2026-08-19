from __future__ import annotations

import hashlib

import pytest

from failure_client.api import FakeSimulationGateway
from failure_client.api.artifact_downloader import persist_verified_artifact
from failure_client.config import ClientSettings
from failure_client.contracts import (
    ArtifactRef,
    CapabilitySnapshot,
    ExecutionSummary,
    RegistrySnapshot,
    RemoteJobState,
    RolloutResult,
)
from failure_client.experiments import (
    ExperimentProtocol,
    RolloutCoordinator,
    build_protocol_lock,
    write_protocol_lock,
)
from failure_client.storage import (
    ClientRepository,
    RolloutAttemptState,
    StoreConflictError,
)

from .test_contracts import make_rollout_request


def make_protocol() -> ExperimentProtocol:
    request = make_rollout_request()
    return ExperimentProtocol.model_validate(
        {
            "schema_version": "1.0",
            "experiment": {
                "experiment_id": "exp_001",
                "title": "G1 standing smoke test",
                "research_question": "Can the selected G1 stack complete a standing rollout?",
            },
            "resources": request.resources.model_dump(mode="json"),
            "task": request.task.model_dump(mode="json", by_alias=True),
            "method": {
                "plugin_id": "manual",
                "plugin_version": "0.1.0",
                "config": {},
            },
            "failure_definition": {
                "id": "fd_standing_v1",
                "version": "1.0",
                "config": {},
            },
            "execution": {
                "candidate_budget": 1,
                "repeats_per_candidate": 1,
                "master_seed": 101,
                "maximum_duration_s": 20.0,
            },
            "artifacts": {"video": "always"},
        }
    )


def make_repository(tmp_path, capabilities: CapabilitySnapshot) -> ClientRepository:
    repository = ClientRepository(tmp_path / "client.sqlite")
    protocol = make_protocol()
    lock = build_protocol_lock(protocol, capabilities)
    repository.create_experiment(
        protocol.experiment.experiment_id,
        protocol.model_dump(mode="json", by_alias=True),
        lock.model_dump(mode="json"),
    )
    return repository


def make_gateway(tmp_path, load_contract_fixture) -> FakeSimulationGateway:
    return FakeSimulationGateway(
        capabilities=CapabilitySnapshot.model_validate(
            load_contract_fixture("capabilities_v1.json")
        ),
        registry=RegistrySnapshot.model_validate(load_contract_fixture("registry_v1.json")),
        artifact_dir=tmp_path / "artifacts",
    )


def test_settings_do_not_expose_token(tmp_path):
    settings = ClientSettings.from_env(
        {
            "FAILURE_CLIENT_SERVER_URL": "https://runpod.example",
            "FAILURE_CLIENT_WORKSPACE": str(tmp_path),
            "FAILURE_CLIENT_TOKEN": "super-secret",
        }
    )

    assert settings.database_path == tmp_path / "client.sqlite"
    assert "super-secret" not in repr(settings)
    assert settings.gateway_config().bearer_token == "super-secret"


def test_protocol_lock_is_content_addressed_and_immutable(tmp_path, load_contract_fixture):
    capabilities = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    first = build_protocol_lock(make_protocol(), capabilities)
    second = build_protocol_lock(make_protocol(), capabilities)
    lock_path = tmp_path / "protocol.lock.yaml"

    written = write_protocol_lock(lock_path, first)
    existing = write_protocol_lock(lock_path, second)

    assert written.lock_sha256 == existing.lock_sha256
    different_protocol = make_protocol().model_copy(
        update={
            "execution": make_protocol().execution.model_copy(
                update={"candidate_budget": 2}
            )
        }
    )
    different = build_protocol_lock(different_protocol, capabilities)
    with pytest.raises(ValueError, match="immutable protocol lock"):
        write_protocol_lock(lock_path, different)


def test_attempt_creation_is_durable_and_rejects_changed_request(
    tmp_path,
    load_contract_fixture,
):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    repository = make_repository(tmp_path, gateway.capabilities)
    request = make_rollout_request()

    first = repository.create_rollout_attempt(
        experiment_id="exp_001",
        candidate_id="cand_001",
        repeat_index=0,
        request=request,
    )
    second = repository.create_rollout_attempt(
        experiment_id="exp_001",
        candidate_id="cand_001",
        repeat_index=0,
        request=request,
    )

    assert first.attempt_id == second.attempt_id
    assert first.idempotency_key == second.idempotency_key
    with pytest.raises(StoreConflictError):
        repository.create_rollout_attempt(
            experiment_id="exp_001",
            candidate_id="cand_001",
            repeat_index=0,
            request=make_rollout_request({"changed": True}),
        )


def test_coordinator_recovers_submit_ack_crash_and_ingests_artifact(
    tmp_path,
    load_contract_fixture,
):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    repository = make_repository(tmp_path, gateway.capabilities)
    coordinator = RolloutCoordinator(repository, gateway, sleep=lambda _: None)
    attempt = coordinator.prepare(
        experiment_id="exp_001",
        candidate_id="cand_001",
        repeat_index=0,
        request=make_rollout_request(),
    )

    # The remote Server accepted the request, but the Client crashed before saving job_id.
    remote_acceptance = gateway.submit_rollout(attempt.request, attempt.idempotency_key)
    recovered = coordinator.advance(attempt.attempt_id)
    assert recovered.job_id == remote_acceptance.job_id
    assert recovered.state == RolloutAttemptState.REMOTE_RUNNING

    payload = b"trajectory parquet bytes"
    artifact = ArtifactRef(
        artifact_id="artifact_001",
        kind="state_trajectory",
        format="parquet",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    gateway.artifact_payloads[artifact.artifact_id] = payload
    gateway.complete_rollout(
        RolloutResult(
            job_id=recovered.job_id or "",
            execution=ExecutionSummary(valid=True, status=RemoteJobState.SUCCEEDED),
            artifacts=[artifact],
        )
    )

    ingested = coordinator.advance(attempt.attempt_id)

    assert ingested.state == RolloutAttemptState.INGESTED
    assert ingested.result is not None
    downloaded = list((tmp_path / "artifacts").glob("*.parquet"))
    assert len(downloaded) == 1
    assert downloaded[0].read_bytes() == payload


def test_coordinator_persists_retryable_gateway_error(tmp_path, load_contract_fixture):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    repository = make_repository(tmp_path, gateway.capabilities)
    coordinator = RolloutCoordinator(repository, gateway)
    attempt = coordinator.prepare(
        experiment_id="exp_001",
        candidate_id="cand_001",
        repeat_index=0,
        request=make_rollout_request(),
    )

    accepted = gateway.submit_rollout(attempt.request, attempt.idempotency_key)
    repository.mark_submitted(attempt.attempt_id, accepted.job_id, accepted.status)
    gateway.statuses.pop(accepted.job_id)
    record = coordinator.advance(attempt.attempt_id)

    assert record.state == RolloutAttemptState.INFRASTRUCTURE_ERROR
    assert record.error is not None
    assert record.error["code"] == "JOB_NOT_FOUND"


def test_artifact_checksum_failure_is_retried_without_losing_result(
    tmp_path,
    load_contract_fixture,
):
    class CorruptOnceGateway(FakeSimulationGateway):
        corrupt_once = True

        def download_artifact(self, ref):
            if self.corrupt_once:
                self.corrupt_once = False
                return persist_verified_artifact(ref, b"corrupt", self.artifact_dir)
            return super().download_artifact(ref)

    capabilities = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    gateway = CorruptOnceGateway(
        capabilities=capabilities,
        registry=RegistrySnapshot.model_validate(load_contract_fixture("registry_v1.json")),
        artifact_dir=tmp_path / "artifacts",
    )
    repository = make_repository(tmp_path, gateway.capabilities)
    coordinator = RolloutCoordinator(repository, gateway, sleep=lambda _: None)
    attempt = coordinator.prepare(
        experiment_id="exp_001",
        candidate_id="cand_001",
        repeat_index=0,
        request=make_rollout_request(),
    )
    submitted = coordinator.advance(attempt.attempt_id)
    payload = b"verified trajectory"
    artifact = ArtifactRef(
        artifact_id="artifact_retry",
        kind="state_trajectory",
        format="parquet",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    gateway.artifact_payloads[artifact.artifact_id] = payload
    gateway.complete_rollout(
        RolloutResult(
            job_id=submitted.job_id or "",
            execution=ExecutionSummary(valid=True, status=RemoteJobState.SUCCEEDED),
            artifacts=[artifact],
        )
    )

    first_download = coordinator.advance(attempt.attempt_id)
    recovered = coordinator.advance(attempt.attempt_id)

    assert first_download.state == RolloutAttemptState.RETRY_PENDING
    assert first_download.result is not None
    assert recovered.state == RolloutAttemptState.INGESTED
    assert len(repository.list_artifacts(attempt.attempt_id)) == 1
