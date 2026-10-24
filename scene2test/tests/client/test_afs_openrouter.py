"""OpenRouter AFS transport and durable proposal guards, without network access."""

import json

import httpx
import pytest

from failure_client.methods.autonomous_feedback import SearchBudget
from llm_afs.provider import call, extract_proposal, request_body
from robot_vlm import openrouter

from .test_afs_autonomous import Proposer, reload, setup


def body():
    value = request_body({"case": "crossing"}, {"type": "object", "properties": {}})
    value.update(model="openai/gpt-6-luna", api_provider="openrouter")
    value["max_output_tokens"] = 128000
    return value


def response(content='{"spaces": []}', *, finish_reason="stop"):
    return {
        "id": "chat-test",
        "model": "openai/gpt-6-luna",
        "provider": "OpenAI",
        "usage": {"prompt_tokens": 12, "completion_tokens": 34, "cost": 0.01},
        "choices": [
            {"finish_reason": finish_reason, "message": {"role": "assistant", "content": content}}
        ],
    }


def test_afs_openrouter_wire_and_saved_response(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-test-key")
    requests = []

    def handler(request):
        requests.append(request)
        assert str(request.url) == openrouter.ENDPOINT
        wire = json.loads(request.content)
        assert wire["model"] == "openai/gpt-6-luna"
        assert wire["max_tokens"] == 128000
        assert wire["messages"][0]["role"] == "system"
        assert wire["messages"][1] == {
            "role": "user",
            "content": [{"type": "text", "text": '{"case": "crossing"}'}],
        }
        assert wire["response_format"]["json_schema"]["strict"] is True
        assert wire["provider"] == openrouter.ROUTING
        assert "service_tier" not in wire and "api_provider" not in wire
        return httpx.Response(200, json=response())

    result = call(body(), transport=httpx.MockTransport(handler))
    assert len(requests) == 1
    assert extract_proposal(result) == {"spaces": []}
    assert result["api_provider"] == "openrouter"
    assert result["routed_provider"] == "OpenAI"
    assert result["usage"]["input_tokens"] == 12
    assert result["openrouter_response"]["usage"]["cost"] == 0.01


@pytest.mark.parametrize(
    "wire", [response(finish_reason="length"), response(content="{bad"), {"choices": []}]
)
def test_afs_openrouter_invalid_response_is_returned_for_durable_storage(monkeypatch, wire):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-test-key")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=wire)

    result = call(body(), transport=httpx.MockTransport(handler))
    assert result["openrouter_response"] == wire
    assert len(calls) == 1
    with pytest.raises((ValueError, json.JSONDecodeError)):
        extract_proposal(result)


def test_afs_openrouter_needs_own_key_and_rejects_invalid_budget(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-direct-key")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        call(body())
    with pytest.raises(ValueError, match="provider/model"):
        SearchBudget(afs_api_provider="openrouter")
    with pytest.raises(ValueError, match="omitted service tier"):
        SearchBudget(
            afs_api_provider="openrouter", afs_model="openai/gpt-6-luna", afs_service_tier="default"
        )


def test_afs_openrouter_http_failure_is_single_attempt(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-test-key")
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429, text="fake-test-key")

    with pytest.raises(RuntimeError, match="HTTP 429") as exc:
        call(body(), transport=httpx.MockTransport(handler))
    assert len(calls) == 1
    assert "fake-test-key" not in str(exc.value)


def test_afs_openrouter_saved_response_resumes_without_resending(tmp_path, monkeypatch):
    class OpenRouterProposer(Proposer):
        def __call__(self, body, **kwargs):
            assert body["api_provider"] == "openrouter"
            assert body["model"] == "openai/gpt-6-luna"
            assert body["max_output_tokens"] == 128000
            result = super().__call__(body, **kwargs)
            result.update(api_provider="openrouter", routed_provider="OpenAI")
            return result

    budget = SearchBudget(afs_api_provider="openrouter", afs_model="openai/gpt-6-luna")
    engine, robot, proposer = setup(tmp_path, budget=budget, proposer=OpenRouterProposer())

    def crash(_):
        raise RuntimeError("after saved response")

    monkeypatch.setattr(engine, "_finish_proposal", crash)
    with pytest.raises(RuntimeError, match="after saved response"):
        engine.run(live=True)
    assert len(proposer.calls) == 1 and not robot.calls
    resumed = reload(engine, robot, proposer)
    result = resumed.run(live=True, max_new_attempts=1)
    assert result["attempted"] == 1
    assert len(proposer.calls) == len(robot.calls) == 1
    assert resumed.state["proposals"][0]["returned_api_provider"] == "openrouter"
