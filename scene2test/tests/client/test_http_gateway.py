from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from failure_client.api import HttpGatewayConfig, HttpSimulationGateway
from failure_client.contracts import (
    ArtifactRef,
    CapabilitySnapshot,
    ContractValidationError,
    GatewayHTTPError,
    ResourceRef,
)

from .test_contracts import make_rollout_request


def test_http_gateway_sends_revision_auth_and_idempotency(
    tmp_path,
    load_contract_fixture,
):
    capabilities = load_contract_fixture("capabilities_v1.json")
    scene = load_contract_fixture("scene_snapshot_v1.json")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret-token"
        if request.url.path == "/api/v1/capabilities":
            return httpx.Response(200, json=capabilities)
        if request.url.path == "/api/v1/scenes/scene_001/snapshot":
            assert request.url.params["revision"] == "sha256:scene-v1"
            return httpx.Response(200, json=scene)
        if request.url.path == "/api/v1/rollouts":
            assert request.headers["Idempotency-Key"] == "idem-001"
            body = json.loads(request.content)
            assert body["resources"]["scene"]["revision"] == "sha256:scene-v1"
            request_hash = f"sha256:{hashlib.sha256(request.content).hexdigest()}"
            return httpx.Response(
                202,
                json={
                    "schema_version": "1.0",
                    "job_id": "job_001",
                    "status": "QUEUED",
                    "request_sha256": request_hash,
                    "submitted_at": "2026-08-20T00:00:00Z",
                },
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    with httpx.Client(base_url="https://runpod.example", transport=transport) as client:
        gateway = HttpSimulationGateway(
            HttpGatewayConfig(
                base_url="https://runpod.example",
                bearer_token="secret-token",
                artifact_dir=tmp_path,
            ),
            client=client,
        )
        assert isinstance(gateway.get_capabilities(), CapabilitySnapshot)
        snapshot = gateway.get_scene_snapshot(
            ResourceRef(id="scene_001", revision="sha256:scene-v1")
        )
        accepted = gateway.submit_rollout(make_rollout_request(), "idem-001")

    assert snapshot.scene_revision == "sha256:scene-v1"
    assert accepted.job_id == "job_001"


def test_http_gateway_retries_retryable_status(tmp_path):
    attempts = 0
    delays: list[float] = []

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"status": "ok"})

    with httpx.Client(
        base_url="https://runpod.example",
        transport=httpx.MockTransport(handler),
    ) as client:
        gateway = HttpSimulationGateway(
            HttpGatewayConfig(
                base_url="https://runpod.example",
                artifact_dir=tmp_path,
                max_attempts=2,
            ),
            client=client,
            sleep=delays.append,
        )
        assert gateway.get_health() == {"status": "ok"}

    assert attempts == 2
    assert delays == [0.0]


def test_http_gateway_normalizes_non_retryable_error(tmp_path):
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "error": {
                    "code": "INVALID_INTERVENTION",
                    "message": "unsupported shape",
                    "retryable": False,
                    "request_id": "srv_req_001",
                }
            },
        )

    with httpx.Client(
        base_url="https://runpod.example",
        transport=httpx.MockTransport(handler),
    ) as client:
        gateway = HttpSimulationGateway(
            HttpGatewayConfig(base_url="https://runpod.example", artifact_dir=tmp_path),
            client=client,
        )
        with pytest.raises(GatewayHTTPError) as exc_info:
            gateway.submit_rollout(make_rollout_request(), "idem-001")

    assert exc_info.value.status_code == 422
    assert exc_info.value.code == "INVALID_INTERVENTION"
    assert exc_info.value.retryable is False
    assert exc_info.value.request_id == "srv_req_001"


def test_cross_origin_artifact_download_does_not_forward_token(tmp_path):
    payload = b"video"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "storage.example"
        assert "Authorization" not in request.headers
        return httpx.Response(200, content=payload)

    with httpx.Client(
        base_url="https://runpod.example",
        transport=httpx.MockTransport(handler),
    ) as client:
        gateway = HttpSimulationGateway(
            HttpGatewayConfig(
                base_url="https://runpod.example",
                artifact_dir=tmp_path,
                bearer_token="must-not-leak",
            ),
            client=client,
        )
        local = gateway.download_artifact(
            ArtifactRef(
                artifact_id="video_001",
                kind="video",
                format="mp4",
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                download_url="https://storage.example/signed/video.mp4?token=signed",
            )
        )

    assert local.path.read_bytes() == payload


def test_http_gateway_rejects_wrong_scene_revision(tmp_path, load_contract_fixture):
    scene = load_contract_fixture("scene_snapshot_v1.json")
    scene["scene_revision"] = "sha256:other"

    with httpx.Client(
        base_url="https://runpod.example",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=scene)),
    ) as client:
        gateway = HttpSimulationGateway(
            HttpGatewayConfig(base_url="https://runpod.example", artifact_dir=tmp_path),
            client=client,
        )
        with pytest.raises(ContractValidationError) as exc_info:
            gateway.get_scene_snapshot(
                ResourceRef(id="scene_001", revision="sha256:scene-v1")
            )

    assert exc_info.value.code == "RESOURCE_REVISION_MISMATCH"
