"""Synthetic HTTP only: no real keys, network, API billing, GPU or robot execution."""

import copy
import json
import os
import runpy
import sys

import httpx
import pytest

from robot_vlm.api_transport import DiagnosticError, call
from robot_vlm.debug_log import CURRENT, Journal
from robot_vlm.goal_policy import GoalAction, GoalPolicy
from robot_vlm.openrouter import request_body
from robot_vlm.policy import Geometry, Observation, OpenAIPolicy
from robot_vlm.push_policy import PushPolicy

MODEL = "openai/gpt-6-luna-pro"
PNG = b"\x89PNG\r\n\x1a\nmock"


def obs():
    return Observation(
        state_version=1,
        simulation_time_s=2.0,
        goal_xy_m=[7.0, 0.0],
        base_xyz_m=[1.0, 0.0, 0.74],
        yaw_rad=0.0,
        previous_execution="none",
        camera_name="test",
        camera_fovy_deg=65.0,
        camera_xyz_m=[1.0, 0.0, 1.0],
        camera_rotation_matrix=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        geometry=[
            Geometry(
                object_id="clear_floor",
                center_m=[4.0, 0.0, 0.0],
                size_m=[8.4, 4.4, 0.2],
                rotation_matrix=[1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            )
        ],
    )


def action():
    return GoalAction(
        state_version=1,
        plan_summary="Synthetic test",
        action="navigate_to",
        target_xy_m=[1.4, 0.0],
        skill_request=None,
        vx_mps=0.0,
        vy_mps=0.0,
        yaw_rate_rps=0.0,
        duration_s=3.0,
    )


def response(**changes):
    value = {
        "id": "gen-synthetic",
        "model": MODEL,
        "provider": "Azure",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"command": action().model_dump()}),
                },
            }
        ],
        "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30, "cost": 0.001},
    }
    return value | changes


def body():
    return GoalPolicy(model=MODEL, api_provider="openrouter").body(obs(), PNG)


def invoke(tmp_path, monkeypatch, handler, *, parse=lambda x: x):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-router-test-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-direct-test-secret")
    monkeypatch.setattr("robot_vlm.api_transport.time.sleep", lambda delay: None)
    journal = Journal(tmp_path / "calls.jsonl", 0, read_timeout_s=300, connect_retries=2)
    token = CURRENT.set(journal)
    try:
        return call(
            body(), parse, transport=httpx.MockTransport(handler), api_provider="openrouter"
        )
    finally:
        CURRENT.reset(token)


def test_wire_preserves_image_prompt_schema_and_reasoning_without_mutation():
    original = body()
    before = copy.deepcopy(original)
    result = request_body(original)
    assert original == before
    assert result["messages"][0] == {"role": "system", "content": original["instructions"]}
    parts = result["messages"][1]["content"]
    assert parts[0]["text"] == original["input"][0]["content"][0]["text"]
    assert parts[1]["image_url"]["url"] == original["input"][0]["content"][1]["image_url"]
    assert (
        result["response_format"]["json_schema"]["schema"] == original["text"]["format"]["schema"]
    )
    assert result["response_format"]["json_schema"]["strict"] is True
    assert result["reasoning"] == original["reasoning"]
    assert result["provider"] == {"allow_fallbacks": False, "require_parameters": True}
    assert not {"models", "service_tier", "max_tokens", "plugins"} & result.keys()


def test_real_policy_parser_with_goal_and_push_capabilities(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-router-test-secret")
    seen = []

    def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer fake-router-test-secret"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=response())

    for cls in (GoalPolicy, PushPolicy):
        policy = cls(model=MODEL, api_provider="openrouter", transport=httpx.MockTransport(handler))
        result, meta = policy.decide(obs(), PNG)
        assert result.action == "navigate_to" and result.state_version == 1
        assert meta["origin"] == "openrouter_api" and meta["model"] == MODEL
        assert meta["usage"] == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
        assert meta["response_id"] == "gen-synthetic"
        assert meta["diagnostic"]["routed_provider"] == "Azure"
        assert meta["diagnostic"]["provider_reported_cost"] == 0.001
    assert "PushAction" in json.dumps(seen[-1]["response_format"])


@pytest.mark.parametrize("failure", ["timeout", "http429", "http500", "unknown_connect"])
def test_post_send_or_ambiguous_errors_never_retry_or_switch_provider(
    tmp_path, monkeypatch, failure
):
    requests = []

    def handler(request):
        requests.append(request)
        if failure == "timeout":
            request.extensions["trace"]("http11.send_request_body.complete", {})
            request.extensions["trace"]("http11.receive_response_headers.failed", {})
            raise httpx.ReadTimeout(
                "fake-router-test-secret fake-direct-test-secret", request=request
            )
        if failure == "unknown_connect":
            raise httpx.ConnectError("no proven pre-send trace", request=request)
        return httpx.Response(429 if failure == "http429" else 500)

    with pytest.raises(DiagnosticError) as err:
        invoke(tmp_path, monkeypatch, handler)
    assert len(requests) == 1 and err.value.diagnostic["retry_count"] == 0
    assert err.value.diagnostic["api_provider"] == "openrouter"
    assert err.value.diagnostic.get("usage") is None
    log = (tmp_path / "calls.jsonl").read_text() + json.dumps(err.value.diagnostic)
    assert "fake-router-test-secret" not in log and "fake-direct-test-secret" not in log
    assert requests[0].extensions["timeout"]["read"] == 300


def test_proven_presend_retry_keeps_endpoint_model_body_and_request_id(tmp_path, monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) <= 2:
            request.extensions["trace"]("connection.connect_tcp.failed", {})
            raise httpx.ConnectError("pre-send", request=request)
        return httpx.Response(200, json=response())

    _, meta = invoke(tmp_path, monkeypatch, handler)
    assert len(requests) == 3 and meta["diagnostic"]["retry_count"] == 2
    assert len({r.content for r in requests}) == 1
    assert len({str(r.url) for r in requests}) == 1
    assert len({r.headers["X-Client-Request-Id"] for r in requests}) == 1


@pytest.mark.parametrize(
    "kind,code",
    [
        ("invalid_json", "action_json_error"),
        ("ambiguous", "response_shape_error"),
        ("length", "api_incomplete_response"),
        ("refusal", "api_refusal"),
        ("bad_schema", "action_schema_error"),
    ],
)
def test_invalid_output_preserves_usage_and_stops(tmp_path, monkeypatch, kind, code):
    value = response()
    if kind == "invalid_json":
        value["choices"][0]["message"]["content"] = "not json"
    elif kind == "ambiguous":
        value["choices"].append(copy.deepcopy(value["choices"][0]))
    elif kind == "length":
        value["choices"][0]["finish_reason"] = "length"
    elif kind == "refusal":
        value["choices"][0]["message"]["refusal"] = "declined"
    else:
        value["choices"][0]["message"]["content"] = '{"command": {"action": "teleport"}}'
    from robot_vlm.wire_contract import GoalEnvelope

    with pytest.raises(DiagnosticError) as err:
        invoke(
            tmp_path,
            monkeypatch,
            lambda r: httpx.Response(200, json=value),
            parse=lambda payload: GoalEnvelope.model_validate(payload),
        )
    assert err.value.diagnostic["code"] == code
    assert err.value.diagnostic["usage"]["total_tokens"] == 30
    assert err.value.diagnostic["provider_reported_cost"] == 0.001


def test_router_key_does_not_fall_back_to_openai_key(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-direct-test-secret")
    requests = []
    with pytest.raises(DiagnosticError) as err:
        call(
            body(),
            lambda value: value,
            transport=httpx.MockTransport(lambda request: requests.append(request)),
            api_provider="openrouter",
        )
    assert err.value.diagnostic["code"] == "missing_api_key" and not requests


@pytest.mark.parametrize("cls", [GoalPolicy, PushPolicy, OpenAIPolicy])
def test_wrong_service_tier_or_model_refused_before_any_request(cls):
    with pytest.raises(ValueError):
        cls(model=MODEL, api_provider="openrouter", service_tier="default")
    with pytest.raises(ValueError):
        cls(model="gpt-6-luna", api_provider="openrouter")
    with pytest.raises(ValueError):
        cls(model=MODEL, api_provider="unknown")


def test_openai_default_endpoint_and_service_tier_contract_unchanged(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-direct-test-secret")
    seen = []
    wire = {
        "id": "resp_synthetic",
        "status": "completed",
        "model": "gpt-6-luna",
        "service_tier": "default",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "{}"}],
            }
        ],
    }

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=wire)

    _, meta = call(
        {"model": "gpt-6-luna", "service_tier": "default"},
        lambda x: x,
        transport=httpx.MockTransport(handler),
    )
    assert str(seen[0].url) == "https://api.openai.com/v1/responses"
    assert seen[0].headers["Authorization"] == "Bearer fake-direct-test-secret"
    assert meta["origin"] == "openai_api" and meta["returned_service_tier"] == "default"
    wire["service_tier"] = "flex"
    with pytest.raises(DiagnosticError, match="api_service_tier_mismatch"):
        call(
            {"model": "gpt-6-luna", "service_tier": "default"},
            lambda x: x,
            transport=httpx.MockTransport(handler),
        )


def test_cli_dry_run_does_not_check_keys_create_run_or_load_gpu(tmp_path, monkeypatch, capsys):
    output = tmp_path / "not_created"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_robot_goal_agent.py",
            "--live",
            "--dry-run",
            "--api-provider",
            "openrouter",
            "--model",
            MODEL,
            "--scene-config",
            "config/humanoid_crossing_development.json",
            "--enable-push",
            "--max-calls",
            "10",
            "--response-timeout",
            "300",
            "--output-root",
            str(output),
        ],
    )
    original = os.getenv

    def no_keys(name, *args):
        if name in {"OPENAI_API_KEY", "OPENROUTER_API_KEY"}:
            raise AssertionError("dry-run must not check credentials")
        return original(name, *args)

    monkeypatch.setattr(os, "getenv", no_keys)
    runpy.run_path("tools/run_robot_goal_agent.py")["main"]()
    line = next(line for line in capsys.readouterr().out.splitlines() if line.startswith("PLAN="))
    plan = json.loads(line[5:])
    assert plan["api_provider"] == "openrouter" and plan["model"] == MODEL
    assert plan["credentials_checked"] is False and plan["executed"] is False
    assert plan["api_call_upper_bound"] == 10 and not output.exists()
