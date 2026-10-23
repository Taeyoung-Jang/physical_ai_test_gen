"""Reject contradictory AFS labels in the output schema, before paid execution."""

import copy

import pytest
from jsonschema import Draft202012Validator, ValidationError, validate

from failure_client.methods.autonomous_feedback import selected_probe
from llm_afs import behavior as b
from llm_afs.behavior_request import request

from .test_afs_breadth import broad_engine, point_for_slot
from .test_branch_anchors import engine as branch_engine
from .test_cause_review import cause_engine, reviewed_raw
from .test_failure_directed import make_engine, point, proposal


def reviewed(ctx, *, intent="relief"):
    p, anchor = point_for_slot(ctx, intent=intent)
    raw = reviewed_raw(ctx, p)
    raw["spaces"][0]["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
    return raw


def role_context(tmp_path):
    e = cause_engine(tmp_path)
    e.state["lock"]["plan"]["budget"]["feedback_policy"] = "cause-review-v3"
    _, ctx = e._selection()
    return e, ctx


@pytest.mark.parametrize(
    "allowed",
    [
        ["relief"],
        ["challenge"],
        ["mechanism_transfer"],
        ["challenge", "mechanism_transfer"],
        ["challenge", "mechanism_transfer", "relief"],
    ],
)
def test_output_schema_accepts_only_valid_pairs_and_host_agrees(tmp_path, allowed):
    e, ctx = role_context(tmp_path)
    ctx["failure_objective"]["allowed_intents"] = allowed
    ctx["failure_objective"]["intent_priority"] = allowed
    body = request(ctx, "gpt-6-luna", selection_policy="autonomous_development_endpoint")
    schema = body["text"]["format"]["schema"]
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for intent, expected_mode in b.FAILURE_INTENT_MODES.items():
        raw = reviewed(ctx, intent=intent)
        for mode in ("cross_mechanism", "success_probe"):
            raw["spaces"][0]["mode"] = mode
            expected = intent in allowed and mode == expected_mode
            assert validator.is_valid(raw) is expected, (allowed, intent, mode)
            if expected:
                assert selected_probe(raw, ctx, e._memory())
            else:
                with pytest.raises(ValueError):
                    selected_probe(raw, ctx, e._memory())
    for intent in allowed:
        assert (
            f"intent={intent} MUST use mode={b.FAILURE_INTENT_MODES[intent]}"
            in body["instructions"]
        )
    assert "A combination does NOT imply cross_mechanism" in body["instructions"]
    assert "max_output_tokens" not in body


def test_mixed_response_does_not_hide_a_contradictory_candidate(tmp_path):
    e, ctx = role_context(tmp_path)
    raw = reviewed(ctx, intent="relief")
    raw["spaces"].append(copy.deepcopy(raw["spaces"][0]))
    raw["spaces"][1]["mode"] = "cross_mechanism"
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    with pytest.raises(ValidationError):
        validate(raw, body["text"]["format"]["schema"])
    with pytest.raises(ValueError, match="mode contradicts"):
        selected_probe(raw, ctx, e._memory())


def test_nested_variants_keep_strict_fields_and_dynamic_guards(tmp_path):
    _, ctx = role_context(tmp_path)
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    schema = body["text"]["format"]["schema"]
    assert "anyOf" not in schema
    variants = schema["properties"]["spaces"]["items"]["anyOf"]
    for reference in variants:
        variant = schema["$defs"][reference["$ref"].removeprefix("#/$defs/")]
        props = variant["properties"]
        assert props["axis"]["enum"] == ctx["development_search"]["selectable_axes"]
        assert props["anchor_case_id"]["enum"] == [c["case_id"] for c in ctx["anchor_catalog"]]
        assert (
            props["analysis_evidence_id"]["enum"]
            == ctx["failure_objective"]["behavior_evidence_ids"]
        )
        assert props["target_family"]["enum"] == ctx["failure_objective"]["supported_targets"]

    def walk(node):
        if isinstance(node, dict):
            assert not {"allOf", "oneOf", "if", "then", "else", "not"} & node.keys()
            if node.get("type") == "object":
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


@pytest.mark.parametrize("profile", ["directed", "branch", "expanded", "breadth", "review_v2"])
def test_existing_directed_profiles_use_same_pair_constraint(tmp_path, profile):
    if profile == "directed":
        e = make_engine(tmp_path, outcomes=("PASS", "FAIL"))
    elif profile in {"branch", "expanded"}:
        e = branch_engine(
            tmp_path, **({"taxonomy_profile": "expanded-ten-v1"} if profile == "expanded" else {})
        )
    elif profile == "breadth":
        e = broad_engine(tmp_path)
    else:
        e = cause_engine(tmp_path)
    _, ctx = e._selection()
    if profile == "directed":
        raw = proposal(ctx, point(ctx, intent="relief"))
    else:
        from .test_branch_anchors import branch_point

        p, _ = (
            point_for_slot(ctx, intent="relief")
            if "exploration_allocation" in ctx
            else branch_point(ctx, intent="relief")
        )
        raw = reviewed_raw(ctx, p) if profile == "review_v2" else proposal(ctx, p)
    schema = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")["text"][
        "format"
    ]["schema"]
    validate(raw, schema)
    raw["spaces"][0]["mode"] = "cross_mechanism"
    with pytest.raises(ValidationError):
        validate(raw, schema)


def test_independent_relief_only_context_rejects_live_failure_shape(tmp_path):
    e, ctx = role_context(tmp_path)
    ctx["development_search"].update(mode="independent-afs-discovery-v1", external_history=False)
    ctx["failure_objective"].update(allowed_intents=["relief"], intent_priority=["relief"])
    body = request(ctx, "gpt-6-luna", selection_policy="independent_evaluation_endpoint")
    raw = reviewed(ctx)
    raw["spaces"][0]["mode"] = "cross_mechanism"
    schema = body["text"]["format"]["schema"]
    with pytest.raises(ValidationError):
        validate(raw, schema)
    with pytest.raises(ValueError, match="intent=relief requires mode=success_probe"):
        selected_probe(raw, ctx, e._memory())
    raw["spaces"][0]["mode"] = "success_probe"
    validate(raw, schema)
    assert selected_probe(raw, ctx, e._memory())
