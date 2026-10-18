"""Branch contracts use synthetic outcomes, not measured discovery performance."""

import copy
import json

import pytest
from jsonschema import validate

from clear_path.contracts import GoalRegionFixture
from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from failure_client.methods.branch_anchors import branch_catalog
from llm_afs import behavior as b
from llm_afs.behavior_request import request

from .test_afs_contrast import Robot, fingerprint, source
from .test_failure_directed import point, proposal


def engine(tmp_path, **budget_options):
    paths = [
        source(tmp_path / "pass", scene=GoalRegionFixture(box_lateral_fraction=1.0)),
        source(
            tmp_path / "fail",
            outcome="FAIL",
            scene=GoalRegionFixture(box_lateral_fraction=0.25),
        ),
    ]
    budget = SearchBudget.model_validate(
        {
            "selection_policy": "failure-branch-v3",
            "max_attempts": 3,
            "valid_rollout_target": 2,
            **budget_options,
        }
    )
    root = AutonomousAFS.create(tmp_path / "session", paths, budget, fingerprint_fn=fingerprint)
    return AutonomousAFS(root, runner=Robot(), fingerprint_fn=fingerprint)


def branch_point(ctx, intent="challenge", axis="floor_friction"):
    role = "observed_failure" if intent == "relief" else "success_control"
    anchor = next(c for c in ctx["anchor_catalog"] if c["role"] == role)
    p = point(ctx, axis=axis, intent=intent)
    lo, hi = ctx["allowed_axes"][axis]
    p.update(
        anchor_case_id=anchor["case_id"],
        anchor_rationale="Branch from this recorded outcome, not the latest scene",
        value=max((lo, hi), key=lambda v: abs(v - anchor["parameters"][axis])),
        evidence_refs=anchor["evidence_ids"][:1],
        behavior_refs=anchor["evidence_ids"][:1],
    )
    return p, anchor


@pytest.mark.parametrize("intent", ["challenge", "mechanism_transfer", "relief"])
def test_selected_anchor_not_latest_fail_is_candidate_base(tmp_path, intent):
    e = engine(tmp_path)
    _, ctx = e._selection()
    assert ctx["latest"]["parameters"]["box_lateral_fraction"] == 0.25
    p, anchor = branch_point(ctx, intent)
    raw = proposal(ctx, p)
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    validate(raw, body["text"]["format"]["schema"])
    definition = body["text"]["format"]["schema"]["$defs"]["BranchPoint"]
    assert set(definition["required"]) == set(definition["properties"])
    assert definition["additionalProperties"] is False
    candidate = selected_probe(raw, ctx, e._memory())
    expected = {**anchor["parameters"], p["axis"]: p["value"]}
    assert candidate["parameters"] == expected
    assert candidate["branch_audit"]["anchor_case_id"] == anchor["case_id"]
    assert candidate["branch_audit"]["unchanged_parameters_verified"] is True
    assert candidate["selection_audit"]["anchor_case_id"] == anchor["case_id"]
    assert candidate["parameters"]["box_lateral_fraction"] == (0.25 if intent == "relief" else 1)


@pytest.mark.parametrize("bad", ["role", "unknown", "ref", "missing", "small", "stale"])
def test_branch_gates_reject_invalid_proposals(tmp_path, bad):
    e = engine(tmp_path)
    _, ctx = e._selection()
    p, anchor = branch_point(ctx)
    if bad == "role":
        p["anchor_case_id"] = next(
            a["case_id"] for a in ctx["anchor_catalog"] if a["role"] == "observed_failure"
        )
    elif bad == "unknown":
        p["anchor_case_id"] = "mixed-or-invented"
    elif bad == "ref":
        refs = next(a["evidence_ids"] for a in ctx["anchor_catalog"] if a != anchor)
        p.update(behavior_refs=refs, evidence_refs=refs)
    elif bad == "missing":
        del p["anchor_rationale"]
    elif bad == "small":
        p["value"] = anchor["parameters"][p["axis"]] + 0.001
    raw = proposal(ctx, p)
    if bad == "stale":
        raw["context_sha256"] = "stale"
    with pytest.raises(ValueError):
        selected_probe(raw, ctx, e._memory())


def test_step_is_measured_from_selected_anchor_and_duplicate_scene_rejected(tmp_path):
    e = engine(tmp_path)
    _, ctx = e._selection()
    p, _ = branch_point(ctx, axis="box_lateral_fraction")
    p["value"] = 0.95  # Far from latest .25 but too close to the PASS anchor 1.
    with pytest.raises(ValueError, match="no novel"):
        selected_probe(proposal(ctx, p), ctx, e._memory())
    p["value"] = 0.25  # Existing FAIL, even though branched from PASS.
    with pytest.raises(ValueError, match="no novel"):
        selected_probe(proposal(ctx, p), ctx, e._memory())


def test_two_branches_can_propose_same_axis_value_without_duplicate_space(tmp_path):
    e = engine(tmp_path)
    _, ctx = e._selection()
    p, _ = branch_point(ctx)
    q, _ = branch_point(ctx, "relief")
    q["mode"], q["intent"] = p["mode"], p["intent"]
    # Test only the common duplicate check; role validation is separately mandatory.
    parsed = b.endpoint_proposal(proposal(ctx, p, q), ctx)
    b.validate(parsed, ctx)
    with pytest.raises(ValueError, match="duplicate"):
        b.validate(b.endpoint_proposal(proposal(ctx, p, copy.deepcopy(p)), ctx), ctx)


def test_mixed_and_unpresented_cases_cannot_enter_anchor_catalog(tmp_path):
    e = engine(tmp_path)
    _, ctx = e._selection()
    memory = e._memory()
    for case in memory["cases"]:
        if case["role"] == "success_control":
            case["role"] = "mixed_outcomes"
    branch_catalog(memory, ctx)
    assert ctx["failure_objective"]["allowed_intents"] == ["relief"]
    assert all(a["role"] == "observed_failure" for a in ctx["anchor_catalog"])
    ctx["failure_objective"]["behavior_evidence_ids"] = []
    with pytest.raises(ValueError, match="no unmixed"):
        branch_catalog(memory, ctx)


@pytest.mark.parametrize("interrupt", [False, True])
def test_mock_loop_resume_keeps_branch_and_exposes_audit(tmp_path, monkeypatch, interrupt):
    e = engine(tmp_path)
    calls = []

    def proposer(body, **kwargs):
        ctx = json.loads(body["input"][0]["content"])["context"]
        calls.append(ctx)
        axis = ctx["development_search"]["selectable_axes"][0]
        p, _ = branch_point(ctx, axis=axis)
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(proposal(ctx, p))}],
                }
            ],
        }

    e.proposer = proposer
    if interrupt:

        def crash(_):
            raise RuntimeError("after branch response saved")

        monkeypatch.setattr(e, "_finish_proposal", crash)
        with pytest.raises(RuntimeError, match="branch response"):
            e.run(live=True, max_new_attempts=1)
        assert len(calls) == 1 and not e.runner.calls
        e = AutonomousAFS(e.root, runner=e.runner, proposer=proposer, fingerprint_fn=fingerprint)
    result = e.run(live=True, max_new_attempts=1)
    assert result["attempted"] == 1
    resumed = AutonomousAFS(e.root, runner=e.runner, proposer=proposer, fingerprint_fn=fingerprint)
    assert resumed.state["attempts"][0]["candidate"]["branch_audit"]["anchor_outcome"] == "PASS"
    _, ctx = resumed._selection()
    review = ctx["failure_objective"]["recent_hypothesis_results"][0]
    assert review["branch_audit"]["anchor_outcome"] == "PASS"
    assert "branch_audit" in resumed.report().read_text()
    assert len(calls) == 1
