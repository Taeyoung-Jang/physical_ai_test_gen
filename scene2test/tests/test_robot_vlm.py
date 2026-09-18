import json

import httpx
import pytest

from robot_vlm.policy import (
    Action,
    MockPolicy,
    Observation,
    OpenAIPolicy,
    PolicyError,
    request_body,
    validate_fresh,
)


def obs():
    return Observation(
        state_version=1,
        simulation_time_s=2.0,
        goal_xy_m=[7.0, 0.0],
        base_xyz_m=[1.0, 0.0, 0.74],
        yaw_rad=0.0,
        geometry=[],
        previous_execution="none",
        camera_name="robot",
        camera_fovy_deg=65.0,
        camera_xyz_m=[1.1, 0.0, 1.0],
        camera_rotation_matrix=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
    )


def action(**changes):
    return Action.model_validate(
        dict(
            state_version=1, action="move", vx_mps=0.1, vy_mps=0.0, yaw_rate_rps=0.0, duration_s=1.0
        )
        | changes
    )


PNG = b"\x89PNG\r\n\x1a\ncontract-test"


def test_multimodal_request_and_boundary():
    body = request_body(obs(), PNG)
    assert body["model"] == "gpt-6-astra" and body["store"] is False
    content = body["input"][0]["content"]
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert body["text"]["format"]["strict"]
    assert "reference_path" not in content[0]["text"]
    with pytest.raises(ValueError):
        Observation.model_validate(obs().model_dump() | {"afs_failure_hypothesis": "secret"})
    with pytest.raises(ValueError):
        request_body(obs(), b"not an image")


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "push_object"},
        {"vx_mps": 0.31},
        {"duration_s": 5.0},
        {"vx_mps": float("nan")},
        {"action": "stop"},
        {"hidden_goal": [1, 2]},
    ],
)
def test_invalid_actions_rejected(changes):
    with pytest.raises(ValueError):
        action(**changes)


def test_stale_version_position_and_heading():
    validate_fresh(action(), obs(), [1.0, 0.0, 0.74], 0.0)
    for a, xyz, heading in [
        (action(state_version=0), [1, 0, 0.74], 0),
        (action(), [2, 0, 0.74], 0),
        (action(), [1, 0, 0.74], 0.4),
    ]:
        with pytest.raises(ValueError):
            validate_fresh(a, obs(), xyz, heading)


def response(value=None):
    return {
        "id": "resp_test",
        "status": "completed",
        "model": "gpt-6-astra",
        "usage": {"total_tokens": 100},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps({"command": value or action().model_dump()}),
                    }
                ],
            }
        ],
    }


def test_mock_transport_image_and_no_retry(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    calls = []

    def handler(req):
        calls.append(req)
        assert req.url == "https://api.openai.com/v1/responses"
        assert json.loads(req.content)["input"][0]["content"][1]["type"] == "input_image"
        return httpx.Response(200, json=response())

    result, meta = OpenAIPolicy(transport=httpx.MockTransport(handler)).decide(obs(), PNG)
    assert result == action() and meta["origin"] == "openai_api" and len(calls) == 1
    assert "test-secret" not in json.dumps(meta)


@pytest.mark.parametrize(
    "status,body",
    [
        (401, {"error": "secret echo"}),
        (200, {"status": "incomplete"}),
        (
            200,
            {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "refusal", "refusal": "secret echo"}],
                    }
                ],
            },
        ),
        (200, response({"bad": "secret echo"})),
    ],
)
def test_provider_errors_sanitized(monkeypatch, status, body):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(status, json=body)

    with pytest.raises(PolicyError) as exc:
        OpenAIPolicy(transport=httpx.MockTransport(handler)).decide(obs(), PNG)
    assert "secret" not in str(exc.value) and len(seen) == 1


def test_mock_is_explicit_and_no_network():
    _, metadata = MockPolicy().decide(obs(), PNG)
    assert metadata["origin"] == "mock_fixed_forward"


def test_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(PolicyError, match="missing_api_key"):
        OpenAIPolicy().decide(obs(), PNG)
