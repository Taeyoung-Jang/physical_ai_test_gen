from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from failure_client.contracts import (
    ExecutionSpec,
    InterventionSpec,
    ResearchContext,
    ResourceRef,
    ResourceSelection,
    RobotRef,
    RolloutRequest,
    TaskSpec,
)
from simulation_server.config import ServerConfig
from simulation_server.main import create_app

GROOT_ROOT = Path(__file__).resolve().parents[4] / "GR00T-WholeBodyControl"


def test_server_config_defaults_to_persistent_runtime(monkeypatch):
    monkeypatch.delenv("SIM_SERVER_DATA_ROOT", raising=False)

    assert ServerConfig.from_env().data_root == Path("/workspace/g1_failure/runtime/server")


def _app(tmp_path: Path):
    return create_app(
        ServerConfig(data_root=tmp_path, groot_root=GROOT_ROOT, execution_backend="probe")
    )


def _request(client: TestClient) -> RolloutRequest:
    registry = client.get("/api/v1/registry/snapshot").json()
    revision = registry["scenes"][0]["revision"]
    return RolloutRequest(
        client_request_id="req_001",
        research_context=ResearchContext(
            experiment_id="exp_001", candidate_id="cand_001", method_instance_id="manual_001"
        ),
        resources=ResourceSelection(
            scene=ResourceRef(id="g1_ground", revision=revision),
            robot=RobotRef(id="unitree_g1", profile_id="43dof", revision=revision),
            controller=ResourceRef(id="mock_standing", revision="builtin:pd-standing-v1"),
            policy=ResourceRef(id="hold_pose", revision="builtin:hold-pose-v1"),
        ),
        task=TaskSpec(schema="stand@1.0"),
        interventions=[
            InterventionSpec(
                operation_id="op_000",
                kind="robot_initial_state.set_spawn",
                parameters={
                    "position_m": [0.0, 0.0, 0.8],
                    "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
                },
            )
        ],
        execution=ExecutionSpec(seed=42, maximum_duration_s=0.02),
    )


def test_health_capabilities_and_registry(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/api/v1/health").json()["status"] == "ok"
        capabilities = client.get("/api/v1/capabilities").json()
        registry = client.get("/api/v1/registry/snapshot").json()
        artifact_formats = {
            item["kind"]: item["formats"] for item in capabilities["artifact_formats"]
        }
        assert artifact_formats["rollout_video"] == ["mp4"]
        assert artifact_formats["rollout_preview"] == ["gif"]
        assert artifact_formats["rollout_thumbnail"] == ["png"]
        assert capabilities["render_profiles"] == [
            {"id": "default", "width": 640, "height": 480, "fps": 20}
        ]
        assert capabilities["registry_revision"] == registry["registry_revision"]
        assert registry["scenes"][0]["id"] == "g1_ground"


def test_rollout_is_idempotent_and_produces_reproduction_artifact(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        request = _request(client)
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        first = client.post(
            "/api/v1/rollouts", json=payload, headers={"Idempotency-Key": "idem-001"}
        )
        second = client.post(
            "/api/v1/rollouts", json=payload, headers={"Idempotency-Key": "idem-001"}
        )
        assert first.status_code == 202
        assert second.json()["job_id"] == first.json()["job_id"]
        job_id = first.json()["job_id"]
        result = client.get(f"/api/v1/rollouts/{job_id}/result")
        assert result.status_code == 200
        body = result.json()
        assert body["execution"]["valid"] is False
        assert body["execution"]["termination_reason"] == "PROBE_BACKEND_NO_SIMULATION"
        artifact_id = body["artifacts"][0]["artifact_id"]
        assert client.get(f"/api/v1/artifacts/{artifact_id}").status_code == 200


def test_idempotency_conflict_and_revision_error_are_normalized(tmp_path):
    with TestClient(_app(tmp_path)) as client:
        request = _request(client)
        payload = request.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert (
            client.post(
                "/api/v1/rollouts", json=payload, headers={"Idempotency-Key": "same"}
            ).status_code
            == 202
        )
        payload["execution"]["seed"] = 99
        conflict = client.post(
            "/api/v1/rollouts", json=payload, headers={"Idempotency-Key": "same"}
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
        payload["resources"]["scene"]["revision"] = "sha256:missing"
        missing = client.post("/api/v1/rollouts", json=payload, headers={"Idempotency-Key": "new"})
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "RESOURCE_REVISION_NOT_FOUND"
