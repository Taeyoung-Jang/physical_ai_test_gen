import copy
import json

import pytest
from test_behavior_afs import observation, proposal

from llm_afs import behavior as b
from llm_afs import provider
from llm_afs.behavior_request import recover_legacy, request


def test_hash_is_supplied_and_constrained():
    ctx = b.context(observation())
    body = request(ctx, "gpt-6-astra")
    payload = json.loads(body["input"][0]["content"])
    assert payload == {"context_sha256": b.digest(ctx), "context": json.loads(json.dumps(ctx))}
    assert body["text"]["format"]["schema"]["properties"]["context_sha256"]["enum"] == [
        b.digest(ctx)
    ]
    assert body["model"] == "gpt-6-astra"
    assert body["store"] is False


def test_standalone_prompt_matches_suite_compiler(tmp_path):
    ctx = b.context(observation())
    instructions = request(ctx, "gpt-6-astra")["instructions"]
    assert "Selection policy: standalone-suite-v1." in instructions
    assert "generates both low and high endpoints" in instructions
    assert "not robot executions" in instructions
    assert "bracket's midpoint" in instructions
    assert "campaign-single-endpoint" not in instructions
    assert "Host runs each endpoint" not in instructions
    spaces = proposal(ctx)
    suite = b.compile_suite(ctx, spaces, tmp_path)
    for space in spaces.spaces:
        rows = [r for r in suite["candidates"] if r["axis"] == space.axis]
        assert [r["parameters"][space.axis] for r in rows] == [space.low, space.high]


@pytest.mark.parametrize(
    ("selection_policy", "schema"),
    [
        ("standalone_suite", "behavior-campaign-feedback-v1"),
        ("campaign_single_endpoint", "behavior-afs-context-v2"),
        ("standalone_suite", "unknown-context"),
        ("campaign_single_endpoint", "unknown-context"),
    ],
)
def test_selection_policy_rejects_mismatched_context(selection_policy, schema):
    ctx = {**b.context(observation()), "schema_version": schema}
    with pytest.raises(ValueError, match="selection policy does not match context schema"):
        request(ctx, "gpt-6-astra", selection_policy=selection_policy)


def test_unknown_selection_policy_rejected():
    with pytest.raises(ValueError, match="unknown behavior AFS selection policy"):
        request(b.context(observation()), "gpt-6-astra", selection_policy="unknown")


def legacy(root, ctx):
    raw = proposal(ctx).model_dump()
    raw["context_sha256"] = "model-invented"
    b.write(root / "context.json", ctx)
    b.write(root / "request.json", provider.request_body(ctx, b.Proposal.model_json_schema()))
    b.write(root / "proposal.json", raw)
    b.write(
        root / "response.json",
        {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        },
    )
    return raw


def test_explicit_legacy_recovery_preserves_original(tmp_path):
    ctx = b.context(observation())
    raw = legacy(tmp_path, ctx)
    fixed, audit = recover_legacy(tmp_path, ctx)
    b.validate(b.Proposal.model_validate(fixed), ctx)
    assert fixed["spaces"] == raw["spaces"]
    assert b.read(tmp_path / "proposal.json") == raw
    assert audit["api_called"] is False
    with pytest.raises(ValueError, match="stale"):
        b.validate(b.Proposal.model_validate(raw), ctx)


@pytest.mark.parametrize("changed", ["context", "request", "proposal"])
def test_mismatch_not_repaired(tmp_path, changed):
    ctx = b.context(observation())
    legacy(tmp_path, ctx)
    if changed == "context":
        ctx = copy.deepcopy(ctx)
        ctx["latest"]["reason"] = "changed"
    else:
        file = tmp_path / (changed + ".json")
        value = b.read(file)
        if changed == "request":
            value["input"][0]["content"] = "{}"
        else:
            value["spaces"][0]["low"] = 0.8
        file.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        recover_legacy(tmp_path, ctx)
