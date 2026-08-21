from __future__ import annotations

import hashlib

import pytest

from failure_client.api import FakeSimulationGateway, SimulationGateway
from failure_client.contracts import (
    ArtifactIntegrityError,
    ArtifactRef,
    CapabilitySnapshot,
    ExecutionSummary,
    GatewayHTTPError,
    RegistrySnapshot,
    RemoteJobState,
    ResourceRef,
    RolloutResult,
    SceneSnapshot,
)

from .test_contracts import make_rollout_request


def make_gateway(tmp_path, load_contract_fixture) -> FakeSimulationGateway:
    capabilities = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    registry = RegistrySnapshot.model_validate(load_contract_fixture("registry_v1.json"))
    scene = SceneSnapshot.model_validate(load_contract_fixture("scene_snapshot_v1.json"))
    return FakeSimulationGateway(
        capabilities=capabilities,
        registry=registry,
        artifact_dir=tmp_path,
        scene_snapshots={(scene.scene_id, scene.scene_revision): scene},
    )


def test_fake_gateway_is_a_simulation_gateway(tmp_path, load_contract_fixture):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    assert isinstance(gateway, SimulationGateway)
    assert gateway.get_scene_snapshot(
        ResourceRef(id="scene_001", revision="sha256:scene-v1")
    ).scene_id == "scene_001"


def test_submit_is_idempotent_and_detects_payload_conflict(tmp_path, load_contract_fixture):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    request = make_rollout_request()

    first = gateway.submit_rollout(request, "idem-001")
    second = gateway.submit_rollout(request, "idem-001")

    assert first.job_id == second.job_id
    with pytest.raises(GatewayHTTPError) as exc_info:
        gateway.submit_rollout(make_rollout_request({"target": [1, 2, 3]}), "idem-001")
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "IDEMPOTENCY_CONFLICT"


def test_fake_gateway_tracks_completion(tmp_path, load_contract_fixture):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    accepted = gateway.submit_rollout(make_rollout_request(), "idem-001")
    gateway.set_job_status(accepted.job_id, RemoteJobState.RUNNING)
    assert gateway.get_rollout_status(accepted.job_id).status == RemoteJobState.RUNNING

    result = RolloutResult(
        job_id=accepted.job_id,
        execution=ExecutionSummary(valid=True, status=RemoteJobState.SUCCEEDED),
        task_facts={"target_reached": False},
    )
    gateway.complete_rollout(result)

    assert gateway.get_rollout_result(accepted.job_id) == result
    assert gateway.get_rollout_status(accepted.job_id).status == RemoteJobState.SUCCEEDED


def test_fake_gateway_verifies_artifact_bytes(tmp_path, load_contract_fixture):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    payload = b"verified trajectory"
    gateway.artifact_payloads["artifact_001"] = payload
    ref = ArtifactRef(
        artifact_id="artifact_001",
        kind="state_trajectory",
        format="parquet",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )

    local = gateway.download_artifact(ref)

    assert local.path.read_bytes() == payload
    assert local.sha256 == ref.sha256

    bad_ref = ref.model_copy(update={"size_bytes": len(payload) + 1})
    with pytest.raises(ArtifactIntegrityError) as exc_info:
        gateway.download_artifact(bad_ref)
    assert exc_info.value.retryable is True

