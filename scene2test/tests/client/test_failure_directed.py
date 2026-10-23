"""Synthetic failure-seeking contracts, not evidence of real AFS discovery gains."""

import copy
import json

import pytest
from jsonschema import validate

from clear_path.contracts import GoalRegionFixture
from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe, selection
from llm_afs import behavior as b
from llm_afs.behavior_request import request

from .test_afs_contrast import Robot, fingerprint, source


def make_engine(tmp_path, outcomes=("PASS", "PASS")):
    paths = [
        source(tmp_path / f"baseline{i}", outcome=outcome, scene=GoalRegionFixture())
        for i, outcome in enumerate(outcomes)
    ]
    budget = SearchBudget(
        selection_policy="failure-directed-v2",
        max_attempts=4,
        valid_rollout_target=3,
        max_attempts_per_axis=2,
    )
    root = AutonomousAFS.create(tmp_path / "session", paths, budget, fingerprint_fn=fingerprint)
    return AutonomousAFS(
        root, runner=Robot(), proposer=DirectedProposer(), fingerprint_fn=fingerprint
    )


def point(ctx, *, axis=None, intent="challenge", family="collision"):
    axis = axis or ctx["development_search"]["selectable_axes"][0]
    lo, hi = ctx["allowed_axes"][axis]
    base = ctx["latest"]["parameters"][axis]
    value = max((lo, hi), key=lambda v: abs(v - base))
    refs = ctx["failure_objective"]["behavior_evidence_ids"][:1]
    return {
        "mode": "success_probe" if intent == "relief" else "cross_mechanism",
        "axis": axis,
        "value": value,
        "evidence_refs": refs,
        "behavior_refs": refs,
        "intent": intent,
        "target_family": family,
        "hypothesis": "synthetic behavior challenge",
        "alternative": "successful recovery",
        "falsification": "PASS with unchanged effective navigation weakens prediction",
        "vulnerability": "Observed direct navigation succeeds; difficulty is a new conjecture",
        "failure_prediction": (
            "The changed scene may prevent measured arrival within the same budget"
        ),
        "change_rationale": "Synthetic direction for test only, not a physical capability claim",
    }


def proposal(ctx, *points):
    return {"context_sha256": b.digest(ctx), "spaces": list(points or [point(ctx)])}


class DirectedProposer:
    def __init__(self):
        self.calls = []

    def __call__(self, body, **kwargs):
        self.calls.append(copy.deepcopy(body))
        ctx = json.loads(body["input"][0]["content"])["context"]
        axis = min(
            ctx["development_search"]["selectable_axes"],
            key=lambda a: ctx["development_search"]["axis_attempts"][a],
        )
        raw = proposal(ctx, point(ctx, axis=axis))
        validate(raw, body["text"]["format"]["schema"])
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        }


def test_all_pass_evidence_still_seeks_failure_with_strict_schema(tmp_path):
    engine = make_engine(tmp_path)
    _, ctx = engine._selection()
    objective = ctx["failure_objective"]
    assert objective["observed_pass"] == 2 and objective["observed_fail"] == 0
    assert ctx["remaining_valid_budget"] == 3
    assert ctx["development_search"]["remaining_attempts"] == 4
    assert "relief" not in objective["allowed_intents"]
    assert objective["measured_discovered_families"] == []
    assert objective["behavior_observations"][0]["goal_outcome"] == "PASS"
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    raw = proposal(ctx)
    validate(raw, body["text"]["format"]["schema"])
    schema = body["text"]["format"]["schema"]
    definition = schema["$defs"]["FailurePoint"]
    assert definition["additionalProperties"] is False
    assert set(definition["required"]) == set(definition["properties"])
    assert "low" not in definition["properties"]
    assert (
        "NONCOMPLETION" in body["instructions"]
        and "PASS is useful evidence" in body["instructions"]
    )
    assert "max_output_tokens" not in body
    assert selected_probe(raw, ctx, engine._memory())["evidence"]["target_family"] == "collision"


@pytest.mark.parametrize(
    "bad",
    [
        "missing_prediction",
        "case_only",
        "unknown_episode",
        "unlisted_ref",
        "relief",
        "mode",
        "unsupported",
        "small",
        "bounds",
        "stale",
    ],
)
def test_invalid_failure_hypotheses_rejected(tmp_path, bad):
    engine = make_engine(tmp_path)
    _, ctx = engine._selection()
    p = point(ctx)
    raw = proposal(ctx, p)
    if bad == "missing_prediction":
        del p["failure_prediction"]
    elif bad == "case_only":
        p["behavior_refs"] = ["case_memory"]
    elif bad == "unknown_episode":
        p["behavior_refs"] = ["invented"]
    elif bad == "unlisted_ref":
        p["evidence_refs"] = ["case_memory"]
    elif bad == "relief":
        p.update(intent="relief", mode="success_probe")
    elif bad == "mode":
        p["mode"] = "success_probe"
    elif bad == "unsupported":
        p["target_family"] = "human_safety_risk"
    elif bad == "small":
        p["value"] = ctx["latest"]["parameters"][p["axis"]] + 0.01
    elif bad == "bounds":
        p["value"] = 999.0
    else:
        raw["context_sha256"] = "stale"
    with pytest.raises(ValueError):
        selected_probe(raw, ctx, engine._memory())


def test_promising_used_axis_remains_eligible_and_missing_family_ranks_first(tmp_path):
    engine = make_engine(tmp_path)
    memory = engine._memory()
    attempts = [
        {"candidate": {"axis": "box_mass_kg", "stage": "discovery", "evidence": {}}},
        {"candidate": {"axis": "floor_friction", "stage": "discovery", "evidence": {}}},
    ]
    _, ctx = selection(memory, attempts, engine.budget, engine.cfg.scene_schema)
    assert "box_mass_kg" in ctx["development_search"]["selectable_axes"]
    assert "floor_friction" not in ctx["development_search"]["selectable_axes"]
    # Synthetic host ranking fixture, not an observed family-discovery claim.
    ctx["failure_objective"]["missing_supported_families"] = ["goal_occupied"]
    a = point(ctx, axis="box_mass_kg", family="collision")
    c = point(ctx, axis="corridor_width_m", family="goal_occupied")
    picked = selected_probe(proposal(ctx, a, c), ctx, memory)
    assert picked["evidence"]["target_family"] == "goal_occupied"
    assert picked["selection_audit"]["eligible_predictions"]


def test_relief_requires_fail_and_has_cooldown(tmp_path):
    engine = make_engine(tmp_path, ("FAIL", "FAIL"))
    _, ctx = engine._selection()
    assert ctx["failure_objective"]["intent_priority"][0] == "relief"
    candidate = selected_probe(proposal(ctx, point(ctx, intent="relief")), ctx, engine._memory())
    _, after = selection(
        engine._memory(), [{"candidate": candidate}], engine.budget, engine.cfg.scene_schema
    )
    assert "relief" not in after["failure_objective"]["allowed_intents"]


def test_live_loop_mock_resume_predictions_never_become_discovery(tmp_path):
    engine = make_engine(tmp_path)
    robot, proposer = engine.runner, engine.proposer
    result = engine.run(live=True, max_new_attempts=1)
    assert result["pass"] == 1 and result["fail"] == 0
    assert result["new_only_discovery_metrics"]["groups"][0]["discovered_family_count"] == 0
    resumed = AutonomousAFS(
        engine.root, runner=robot, proposer=proposer, fingerprint_fn=fingerprint
    )
    _, ctx = resumed._selection()
    assert ctx["remaining_valid_budget"] == 2
    reviews = ctx["failure_objective"]["recent_hypothesis_results"]
    assert reviews[0]["result"] == "GOAL_FAILURE_NOT_OBSERVED"
    assert reviews[0]["predicted_family"] == "collision"
    assert reviews[0]["observed_primary_family"] is None
    result = resumed.run(live=True)
    assert result["status"] == "COMPLETE" and result["valid"] == 3
    assert len(robot.calls) == len(proposer.calls) == 3
    assert resumed.report().is_file()
    assert all(a["candidate"]["stage"] == "discovery" for a in resumed.state["attempts"])


def test_prediction_failure_or_exclusion_never_proves_cause():
    from failure_client.methods.failure_objective import prediction_review

    attempt = {
        "id": "synthetic",
        "candidate": {
            "axis": "floor_friction",
            "evidence": {"intent": "challenge", "target_family": "collision"},
        },
        "episode": {"status": "VALID", "task_outcome": "FAIL", "attribution": None},
    }
    result = prediction_review(attempt)
    assert result["result"] == "GOAL_FAILURE_OBSERVED_MECHANISM_UNCONFIRMED"
    assert result["observed_primary_family"] is None
    attempt["episode"].update(status="INCONCLUSIVE", task_outcome="INCONCLUSIVE")
    assert prediction_review(attempt)["observed_goal_outcome"] is None


@pytest.mark.parametrize(
    "name,target,attempts",
    [
        ("afs_failure_directed_luna.json", 6, 8),
        ("afs_failure_directed_20_luna.json", 20, 24),
    ],
)
def test_versioned_configs(name, target, attempts):
    from pathlib import Path

    budget = SearchBudget.model_validate(json.loads((Path("config") / name).read_text()))
    assert budget.valid_rollout_target == target and budget.max_attempts == attempts
    assert budget.selection_policy == "failure-directed-v2"
