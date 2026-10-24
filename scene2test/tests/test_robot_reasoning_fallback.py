import json

import pytest
from test_goal_outcome_runner import runner, setup_loop

from robot_vlm.api_transport import DiagnosticError
from robot_vlm.reasoning_fallback import MODEL, deadline, eligible, next_effort
from robot_vlm.timing import RequestTiming


def length_error(index=0):
    return DiagnosticError(
        "api_incomplete_response",
        {
            "http_status": 200,
            "returned_model": MODEL,
            "incomplete_reason": "max_output_tokens",
            "usage": {"input_tokens": 10, "output_tokens": 128000, "total_tokens": 128010},
            "response_id": f"gen-length-{index}",
        },
    )


def test_verified_ladder_and_bounded_deadline():
    assert eligible("openrouter", MODEL)
    assert not eligible("openai", MODEL) and not eligible("openrouter", MODEL + "-pro")
    assert [next_effort(length_error(), e) for e in ("high", "medium", "low", "none")] == [
        "medium",
        "low",
        "none",
        None,
    ]
    assert deadline(RequestTiming(600), True) == 1200
    assert deadline(RequestTiming(600), False) == 653


@pytest.mark.parametrize(
    "change",
    [
        {"code": "api_timeout"},
        {"http_status": 503},
        {"returned_model": MODEL + "-pro"},
        {"incomplete_reason": "content_filter"},
        {"code": "action_json_error"},
        {"code": "response_deadline"},
        {"http_status": None},
    ],
)
def test_other_errors_never_downgrade(change):
    exc = length_error()
    exc.diagnostic.update(change)
    assert next_effort(exc, "high") is None


def policy_with_errors(monkeypatch, failures):
    policy = setup_loop(monkeypatch, "safe")
    policy.api_provider, policy.model = "openrouter", MODEL
    original = policy.decide
    efforts = []

    def decide(obs, png):
        efforts.append(policy.reasoning_effort)
        if len(efforts) <= failures:
            raise length_error(obs.state_version)
        action, _ = original(obs, png)
        return action, {
            "origin": "mock",
            "model": MODEL,
            "response_id": f"gen-success-{obs.state_version}",
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }

    policy.decide = decide
    return policy, efforts


def test_actual_runner_downgrades_without_executing_partial_output(monkeypatch, tmp_path):
    policy, efforts = policy_with_errors(monkeypatch, failures=3)
    result = runner.run(tmp_path, tmp_path, policy, max_calls=5, response_timeout=600)
    assert efforts == ["high", "medium", "low", "none", "none"]
    assert result["calls_attempted"] == 5
    assert result["valid_execution"]
    events = [json.loads(line) for line in (tmp_path / "decisions.jsonl").read_text().splitlines()]
    retries = [e for e in events if e.get("event") == "reasoning_fallback"]
    assert len(retries) == 3 and all(e["executed"] is False for e in retries)
    assert sum(e.get("execution") == "accepted" for e in events) == 2
    assert not (tmp_path / "pending_call.json").exists()
    protocol = json.loads((tmp_path / "protocol.json").read_text())
    assert protocol["response_deadline_wall_s"] == 1200
    assert protocol["max_output_tokens_per_call"] == 128000
    import hashlib

    from failure_client.evaluation.call_usage import collect_usage

    hashes = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in tmp_path.glob("api_call_*.jsonl")
    }
    hashes["decisions.jsonl"] = hashlib.sha256(
        (tmp_path / "decisions.jsonl").read_bytes()
    ).hexdigest()
    usage = collect_usage(tmp_path, hashes, max_calls=5, attempted=5)
    assert len(usage["calls"]) == 5 and usage["calls_missing_usage"] == 0
    assert sum(c["output_tokens"] for c in usage["calls"]) == 3 * 128000 + 10


@pytest.mark.parametrize(
    "max_calls,failures,expected",
    [(2, 2, ["high", "medium"]), (6, 4, ["high", "medium", "low", "none"])],
)
def test_exhausted_budget_or_none_length_stops(
    monkeypatch, tmp_path, max_calls, failures, expected
):
    policy, efforts = policy_with_errors(monkeypatch, failures)
    result = runner.run(tmp_path, tmp_path, policy, max_calls=max_calls, response_timeout=600)
    assert efforts == expected and not result["valid_execution"]
    assert result["reason"] == "api_incomplete_response"
    assert result["live_actions_accepted"] == 0


@pytest.mark.parametrize("code", ["api_timeout", "api_http_503", "action_json_error"])
def test_actual_runner_nonlength_error_does_not_retry(monkeypatch, tmp_path, code):
    policy = setup_loop(monkeypatch, "safe")
    policy.api_provider, policy.model = "openrouter", MODEL
    calls = []

    def decide(obs, png):
        calls.append(policy.reasoning_effort)
        raise DiagnosticError(code, {"code": code})

    policy.decide = decide
    result = runner.run(tmp_path, tmp_path, policy, max_calls=20, response_timeout=600)
    assert calls == ["high"]
    assert result["reason"] == code and result["calls_attempted"] == 1
    assert not result["valid_execution"]
