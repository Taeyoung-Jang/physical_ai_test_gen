"""Mock-only OpenRouter AFS and versioned bootstrap transition guards."""

import json
import sys
from pathlib import Path

import httpx
import pytest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
sys.path.insert(0, str(PROJECT / "tools"))
import migrate_robot_arm_openrouter as migration  # noqa: E402

from robot_arm import openrouter, search  # noqa: E402
from robot_arm.placement import save  # noqa: E402


@pytest.fixture
def cfg(tmp_path):
    c = search.read(PROJECT / "config/robot_arm_placement_wide.json")
    c["seeds"] = [7]
    model = tmp_path / "model"
    model.mkdir()
    (model / "weight.bin").write_bytes(b"fake")
    c["robot"]["model_path"] = str(model)
    return c


def router(c):
    return dict(c, afs_api_provider="openrouter", afs_model=openrouter.MODEL, afs_service_tier=None)


def raw(positions, **overrides):
    result = {
        "id": "gen_fake",
        "model": openrouter.MODEL,
        "provider": "OpenAI",
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "cost": 0.0001},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"positions": positions, "hypothesis": "test"}),
                },
            }
        ],
    }
    result.update(overrides)
    return result


def prepare(root, c):
    root.mkdir()
    src = root.parent / "frozen.py"
    src.write_text("# mock")
    save(root / "manifest.json", search.freeze(c, [src]))
    (root / "manifest.sha256").write_text(search.sha(root / "manifest.json"))
    return root


def test_wire_schema_and_routing_do_not_leak_key(cfg):
    c = router(cfg)
    body = search.proposal_body(c, [])
    assert body["model"] == openrouter.MODEL
    assert body["provider"] == {"allow_fallbacks": False, "require_parameters": True}
    assert body["response_format"]["json_schema"]["strict"]
    assert "service_tier" not in body and "Authorization" not in body
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1]["content"][0]["type"] == "text"
    search.validate(c)


def test_single_call_uses_only_router_key(cfg, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-router-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-direct-key")
    body = search.proposal_body(router(cfg), [])
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer fake-router-key"
        return httpx.Response(200, json=raw(search.uniform(cfg, 7, 2)))

    result = openrouter.call(body, transport=httpx.MockTransport(handle))
    assert len(calls) == 1 and result["provider"] == "OpenAI"
    assert "fake-router-key" not in json.dumps(body)
    assert search.extract(router(cfg), result)["positions"] == search.uniform(cfg, 7, 2)


@pytest.mark.parametrize("failure", ["read_timeout", "http_429"])
def test_transport_and_http_are_never_retried(cfg, monkeypatch, failure):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake-router-key")
    calls = []

    def handle(request):
        calls.append(request)
        if failure == "read_timeout":
            raise httpx.ReadTimeout("fake timeout", request=request)
        return httpx.Response(429)

    with pytest.raises(RuntimeError, match="no resend"):
        openrouter.call(
            search.proposal_body(router(cfg), []), transport=httpx.MockTransport(handle)
        )
    assert len(calls) == 1


@pytest.mark.parametrize("which", ["model", "length", "refusal", "tools", "error", "json"])
def test_bad_response_is_not_repaired(cfg, which):
    value = raw(search.uniform(cfg, 7, 2))
    if which == "model":
        value["model"] = "other/model"
    elif which == "length":
        value["choices"][0]["finish_reason"] = "length"
    elif which == "refusal":
        value["choices"][0]["message"]["refusal"] = "no"
    elif which == "tools":
        value["choices"][0]["message"]["tool_calls"] = [{}]
    elif which == "error":
        value["error"] = {"message": "failure"}
    else:
        value["choices"][0]["message"]["content"] = "not JSON"
    with pytest.raises((ValueError, TypeError)):
        search.extract(router(cfg), value)


def test_cached_raw_response_resumes_without_resend(cfg, tmp_path):
    c = router(cfg)
    root = prepare(tmp_path / "campaign", c)

    def passing(*a):
        return {"status": "VALID", "task_outcome": "PASS"}

    search.run(root, passing, lambda _: pytest.fail("bootstrap calls API"), max_new=4)
    d = root / "seed_7/afs/attempt_00002"
    d.mkdir()
    save(d / "request.json", search.proposal_body(c, search.history_for(root, 7, "afs")))
    save(d / "response.json", raw(search.uniform(c, 7, 2)))
    result = search.run(root, passing, lambda _: pytest.fail("resend"), max_new=1)
    assert result["totals"]["afs"]["known_input_tokens"] == 20
    assert result["totals"]["afs"]["known_output_tokens"] == 5


def bootstrap_source(tmp_path, c):
    root = prepare(tmp_path / "source", c)
    for i in range(c["bootstrap"]):
        for method in c["methods"]:
            d = root / f"seed_7/{method}/attempt_{i:05d}"
            d.mkdir(parents=True)
            candidate = {
                "positions": search.uniform(c, 7, i),
                "scene_seed": search.scene_seed(7, i),
            }
            for name in ["candidate.json", "robot_intent.json"]:
                save(d / name, candidate)
            result = {"status": "VALID", "task_outcome": "PASS", "steps": [1]}
            for name in ["receipt.json", "result.json"]:
                save(d / name, result)
            save(
                d / "initial_state.json",
                {"valid": True, "requested": candidate["positions"], "after": {}},
            )
            (d / "trace.jsonl").write_text(json.dumps({"success": True}) + "\n")
    pending = root / "seed_7/afs/attempt_00002"
    pending.mkdir()
    save(pending / "request.json", search.proposal_body(c, search.history_for(root, 7, "afs")))
    m = search.read(root / "manifest.json")
    audit = tmp_path / "audit.json"
    save(
        audit,
        {
            "manifest_sha256": search.sha(root / "manifest.json"),
            "changed_sources": [],
            "source": str(root.resolve()),
            "verified_source_hashes": m["source_hashes"],
        },
    )
    return root, audit


def test_transition_preserves_completed_bootstrap_and_quarantines_unsent_intent(
    cfg, tmp_path, monkeypatch
):
    source, audit = bootstrap_source(tmp_path, cfg)
    before = {str(p): search.sha(p) for p in source.rglob("*") if p.is_file()}
    monkeypatch.setattr(migration.cli, "sources", lambda c: [tmp_path / "frozen.py"])
    output = tmp_path / "destination"
    transition = migration.prepare(source, output, audit, confirmed_pre_send_failure=True)
    assert transition["inherited_bootstrap_robot_attempts"] == 4
    assert transition["remaining_robot_attempt_cap"] == 4
    assert transition["new_openrouter_request_cap"] == 2
    assert not list(output.glob("seed_*/*/attempt_*/request.json"))
    assert before == {str(p): search.sha(p) for p in source.rglob("*") if p.is_file()}
    search.verify(output)

    def fail_runner(*a):
        pytest.fail("API request only, no rollout expected")

    def stop_api(body):
        assert body["model"] == openrouter.MODEL
        raise RuntimeError("intent retained")

    with pytest.raises(RuntimeError, match="intent retained"):
        search.run(output, fail_runner, stop_api)
    assert len(list(output.glob("seed_*/*/attempt_*/robot_intent.json"))) == 4
    assert len(list(output.glob("seed_*/*/attempt_*/request.json"))) == 1


@pytest.mark.parametrize("problem", ["unconfirmed", "response", "candidate", "bad_trace"])
def test_transition_rejects_ambiguous_or_changed_history(cfg, tmp_path, problem):
    source, audit = bootstrap_source(tmp_path, cfg)
    pending = source / "seed_7/afs/attempt_00002"
    if problem == "response":
        save(pending / "response.json", {})
    elif problem == "candidate":
        save(pending / "candidate.json", {})
    elif problem == "bad_trace":
        (source / "seed_7/afs/attempt_00000/trace.jsonl").write_text("{}\n{}\n")
    with pytest.raises((ValueError, KeyError)):
        migration.inspect(source, audit, problem != "unconfirmed")


def test_router_live_missing_key_preflight_does_not_create_intent(cfg, tmp_path, monkeypatch):
    import run_robot_arm_search as cli

    root = tmp_path / "empty"
    root.mkdir()
    save(root / "manifest.json", {"mode": "paired_development"})
    monkeypatch.setattr(cli.search, "verify", lambda _: router(cfg))
    monkeypatch.setattr(openrouter.os, "environ", {})
    monkeypatch.setattr(sys, "argv", ["runner", "run", "--live", "--output", str(root)])
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        cli.main()
    assert list(root.iterdir()) == [root / "manifest.json"]
