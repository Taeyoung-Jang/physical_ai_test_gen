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
