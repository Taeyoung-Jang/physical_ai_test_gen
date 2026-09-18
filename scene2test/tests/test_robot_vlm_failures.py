"""Regression coverage for wire/local mismatch, redacted diagnostics and finalization."""

import hashlib
import json
import os
from pathlib import Path

import httpx
import jsonschema
import pytest

from robot_vlm.api_transport import DiagnosticError, call
from robot_vlm.goal_policy import GoalAction
from robot_vlm.wire_contract import GoalEnvelope, VelocityEnvelope, schema


def command(action="move", **overrides):
    return (
        dict(
            state_version=0,
            plan_summary="test",
            action=action,
            target_xy_m=[1.0, 0.0] if action in {"navigate_to", "plan_path"} else None,
            skill_request="push box" if action == "request_skill" else None,
            vx_mps=0.0,
            vy_mps=0.0,
            yaw_rate_rps=0.0,
            duration_s=1.0,
        )
        | overrides
    )


def parse(value):
    return GoalAction.model_validate(GoalEnvelope.model_validate(value).command.model_dump())


@pytest.mark.parametrize(
    "action", ["navigate_to", "plan_path", "move", "observe", "stop", "request_skill"]
)
def test_all_action_variants_share_wire_and_local_constraints(action):
    value = {"command": command(action)}
    jsonschema.validate(value, schema(GoalEnvelope))
    assert parse(value).action == action


@pytest.mark.parametrize(
    "cmd",
    [
        command("move", duration_s=3.0),
        command("move", target_xy_m=[1.0, 0.0]),
        command("navigate_to", target_xy_m=None),
        command("navigate_to", target_xy_m=[1.0]),
        command("navigate_to", target_xy_m=[1.0, 0.0, 2.0]),
        command("navigate_to", vx_mps=0.1),
        command("observe", vy_mps=0.1),
        command("stop", skill_request="bad"),
        command("request_skill", skill_request=""),
        command("request_skill", skill_request="x" * 601),
        command("navigate_to", duration_s=10.1),
        command("move", vx_mps=0.31),
    ],
)
def test_invalid_commands_rejected_both_sides(cmd):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"command": cmd}, schema(GoalEnvelope))
    with pytest.raises(ValueError):
        parse({"command": cmd})


def test_navigation_duration_not_restricted_to_move_limit():
    value = {"command": command("navigate_to", duration_s=10.0)}
    jsonschema.validate(value, schema(GoalEnvelope))
    assert parse(value).duration_s == 10


def test_velocity_passive_schema_enforces_zero():
    value = {
        "command": dict(
            state_version=0,
            action="observe",
            vx_mps=0.1,
            vy_mps=0.0,
            yaw_rate_rps=0.0,
            duration_s=1.0,
        )
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, schema(VelocityEnvelope))


def envelope(text=None):
    return {
        "id": "resp_test",
        "status": "completed",
        "usage": {"total_tokens": 123},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": text or json.dumps({"command": command()})}
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "case,expected",
    [
        ("timeout", "api_timeout"),
        ("connect", "api_transport_error"),
        ("http", "api_http_401"),
        ("json", "response_json_error"),
        ("shape", "response_shape_error"),
        ("incomplete", "api_incomplete_response"),
        ("refusal", "api_refusal"),
        ("ambiguous", "response_ambiguous_output"),
        ("action_json", "action_json_error"),
        ("schema", "action_schema_error"),
    ],
)
def test_failure_categories_redact_secret_and_do_not_retry(monkeypatch, case, expected):
    secret = "sk-test-do-not-persist"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    seen = []

    def handler(req):
        seen.append(req)
        if case == "timeout":
            raise httpx.ReadTimeout(secret, request=req)
        if case == "connect":
            raise httpx.ConnectError(secret, request=req)
        if case == "http":
            return httpx.Response(401, text=secret)
        if case == "json":
            return httpx.Response(200, text=secret)
        values = {
            "shape": [],
            "incomplete": {
                "status": "incomplete",
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            "refusal": {
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "refusal", "refusal": secret}],
                    }
                ],
            },
            "ambiguous": {"status": "completed", "output": []},
            "action_json": envelope(secret),
            "schema": envelope(
                json.dumps({"command": command("move", duration_s=3.0) | {secret: secret}})
            ),
        }
        return httpx.Response(200, json=values[case], headers={"x-request-id": "req_test"})

    with pytest.raises(DiagnosticError) as caught:
        call({"model": "gpt-6-astra"}, parse, transport=httpx.MockTransport(handler))
    assert str(caught.value) == expected and len(seen) == 1
    assert secret not in json.dumps(caught.value.diagnostic)
    if case == "schema":
        assert caught.value.diagnostic["validation_errors"]
        assert caught.value.diagnostic["response_id"] == "resp_test"
        assert caught.value.diagnostic["usage"] == {"total_tokens": 123}


def test_valid_response_preserves_action_and_metadata(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    action, meta = call(
        {"model": "gpt-6-astra"},
        parse,
        transport=httpx.MockTransport(lambda req: httpx.Response(200, json=envelope())),
    )
    assert action.duration_s == 1 and meta["diagnostic"]["stage"] == "completed"


@pytest.mark.skipif(os.getenv("RUN_ROBOT_ERROR_GPU") != "1", reason="explicit GPU fault smoke only")
def test_gpu_policy_failure_finalizes_video_and_diagnostics():
    from datetime import datetime, timezone

    from robot_vlm.goal_policy import GoalMock
    from robot_vlm.goal_runner import run

    class FaultPolicy(GoalMock):
        def decide(self, observation, png):
            raise DiagnosticError("action_schema_error", {"stage": "action_validation"})

    root = Path("/workspace/g1_failure/runtime/robot_error_checks") / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    result = run(
        root,
        Path("/workspace/g1_failure/src/GR00T-WholeBodyControl"),
        FaultPolicy(),
        max_calls=1,
        max_seconds=4,
    )
    assert not result["valid_execution"] and result["reason"] == "action_schema_error"
    assert (
        json.loads((root / "failure_diagnostic.json").read_text())["stage"] == "action_validation"
    )
    assert (root / "terminal_state.json").exists()
    import imageio.v2 as imageio

    with imageio.get_reader(root / "rollout.mp4") as video:
        assert video.get_data(0).shape == (540, 960, 3)
    for item in json.loads((root / "manifest.json").read_text())["artifacts"]:
        assert hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    print(f"ERROR_SMOKE={root}")


@pytest.mark.skipif(
    os.getenv("RUN_ROBOT_ERROR_GPU") != "1", reason="explicit GPU pending-call smoke"
)
def test_gpu_pending_response_recorded_but_never_executed():
    import time
    from datetime import datetime, timezone

    from robot_vlm.goal_policy import GoalMock
    from robot_vlm.goal_runner import run

    class Delayed(GoalMock):
        def decide(self, observation, png):
            time.sleep(3)
            return super().decide(observation, png)

    root = Path("/workspace/g1_failure/runtime/robot_error_checks") / datetime.now(
        timezone.utc
    ).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    result = run(
        root,
        Path("/workspace/g1_failure/src/GR00T-WholeBodyControl"),
        Delayed(),
        max_calls=1,
        max_seconds=3,
    )
    assert result["reason"] == "INFERENCE_SIM_BUDGET"
    pending = json.loads((root / "pending_call.json").read_text())
    assert pending["status"] == "completed_after_termination" and pending["executed"] is False
    assert "action" in pending and result["live_actions_accepted"] == 0
    for item in json.loads((root / "manifest.json").read_text())["artifacts"]:
        assert hashlib.sha256((root / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    print(f"PENDING_SMOKE={root}")
