"""Opt-in allocation relevance: synthetic CPU evidence, never performance claims."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import validate

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from failure_client.methods.breadth_policy import allocation, behavior_relevance, reject
from llm_afs.behavior_request import request

from .test_action_search_feedback import entry
from .test_afs_breadth import attempt, broad_engine, point_for_slot
from .test_afs_contrast import fingerprint
from .test_cause_review import reviewed_raw
from .test_discovery_continuation import TransferProposer

AXES = ["floor_friction", "box_mass_kg", "obstacle_1_height_m", "human_x_m"]


def observed(ref="nav", action="navigate_to", **details):
    value = entry({"action": action, **details})
    value["record"].update(evidence_id=ref, status="VALID", task_outcome="PASS")
    return value


def memory(*entries):
    return {"episodes": {e["record"]["evidence_id"]: e for e in entries}}


def relevant_engine(tmp_path, **kwargs):
    return broad_engine(
        tmp_path,
        feedback_policy="cause-review-v3",
        pattern_feedback="trajectory-v1",
        factor_allocation="behavior-relevance-v1",
        anchor_policy="failure-diversity-v4",
        **kwargs,
    )


def test_default_allocator_is_unchanged_and_opt_in_requires_reviewed_trajectory():
    assert SearchBudget().factor_allocation == "balanced-v1"
    with pytest.raises(ValueError, match="requires reviewed trajectory"):
        SearchBudget(factor_allocation="behavior-relevance-v1")
    rows = [attempt(["floor_friction"])]
    assert allocation(rows, AXES)["required_group"] == "object_physics"
    assert "behavior_relevance" not in allocation(rows, AXES)


def test_navigation_absence_defers_mandatory_object_group_not_scene_axes():
    mem = memory(observed())
    before = deepcopy(mem)
    relevance = behavior_relevance(mem)
    slot = allocation([attempt(["floor_friction"])], AXES, relevance=relevance)
    assert slot["required_group"] == "obstacle_geometry"
    assert slot["group_axes"]["object_physics"] == ["box_mass_kg"]
    assert slot["deferred_mandatory_groups"] == ["object_physics"]
    assert relevance["object_physics"]["complete_without_request_evidence_ids"] == ["nav"]
    # Optional interaction remains legal; no blanket ban or parameter-range change.
    slot["required_form"] = "combination"
    assert (
        reject(
            {"form": "combination", "groups": ["obstacle_geometry", "object_physics"]},
            {"target_family": "fall"},
            slot,
        )
        is None
    )
    assert mem == before


@pytest.mark.parametrize("kind", ["partial", "unavailable", "censored", "empty", "missing"])
def test_incomplete_absence_stays_unknown_and_does_not_defer(kind):
    value = observed()
    if kind == "partial":
        value["behavior"]["components"]["actions"] = "PARTIAL"
    elif kind == "unavailable":
        value["behavior"]["components"]["actions"] = "UNAVAILABLE"
    elif kind == "censored":
        value["behavior"]["intervals"][0]["censored"] = True
    elif kind == "empty":
        value["behavior"]["intervals"] = []
    else:
        value["behavior"] = {}
    rel = behavior_relevance(memory(observed("complete"), value))
    assert rel["object_physics"]["status"] == "UNKNOWN"
    assert (
        allocation([attempt(["floor_friction"])], AXES, relevance=rel)["required_group"]
        == "object_physics"
    )


@pytest.mark.parametrize("execution", ["accepted", "rejected"])
def test_request_restores_eligibility_without_physical_success_claim(execution):
    push = observed("push", "push_object", execution=execution, tool_status="rejected")
    push["behavior"]["components"]["actions"] = "PARTIAL"
    rel = behavior_relevance(memory(observed(), push))
    assert rel["object_physics"]["status"] == "REQUEST_OBSERVED"
    assert rel["object_physics"]["request_evidence_ids"] == ["push"]
    assert (
        allocation([attempt(["floor_friction"])], AXES, relevance=rel)["required_group"]
        == "object_physics"
    )


def test_excluded_push_does_not_restore_group_and_quotas_still_charge():
    push = observed("excluded", "push_object")
    push["record"].update(status="INCONCLUSIVE", task_outcome="INCONCLUSIVE")
    rel = behavior_relevance(memory(observed(), push))
    assert rel["object_physics"]["status"] == "NO_REQUEST_OBSERVED"
    rows = [attempt(["floor_friction"], status="INCONCLUSIVE", outcome="INCONCLUSIVE")]
    slot = allocation(rows, AXES, relevance=rel)
    assert slot["group_attempts"]["floor_physics"] == 1
    assert slot["required_form"] == "large"


def test_no_remaining_mandatory_group_does_not_force_object_budget_or_widen_axes():
    rel = behavior_relevance(memory(observed()))
    slot = allocation([], ["box_mass_kg"], relevance=rel)
    assert slot["required_group"] is None
    assert slot["optional_exploration_groups"] == ["object_physics"]
    assert (
        reject({"form": "small", "groups": ["object_physics"]}, {"target_family": "fall"}, slot)
        is None
    )


def test_context_schema_host_and_summary_save_same_relevance(tmp_path):
    engine = relevant_engine(tmp_path)
    _, ctx = engine._selection()
    slot = ctx["exploration_allocation"]
    assert slot["version"] == "behavior-relevance-v1"
    p, anchor = point_for_slot(ctx)
    raw = reviewed_raw(ctx, p)
    raw["spaces"][0]["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    validate(raw, body["text"]["format"]["schema"])
    assert "Behavior-relevance-v1 overrides" in body["instructions"]
    assert "max_output_tokens" not in body
    chosen = selected_probe(raw, ctx, engine._memory())
    assert chosen["selection_audit"]["exploration_allocation"] == slot
    assert (
        engine.summary()["exploration_allocation"]["behavior_relevance"]
        == slot["behavior_relevance"]
    )


def test_saved_response_resume_does_not_redispatch(tmp_path, monkeypatch):
    engine = relevant_engine(tmp_path, max_attempts=1, valid_rollout_target=1)
    proposer = TransferProposer()
    engine.proposer = proposer

    def interrupted(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(engine, "_finish_proposal", interrupted)
    with pytest.raises(KeyboardInterrupt):
        engine.run(live=True)
    path = engine.root / "proposals/proposal_00000/request.json"
    before = path.read_bytes()
    resumed = AutonomousAFS(
        engine.root, runner=engine.runner, proposer=proposer, fingerprint_fn=fingerprint
    )
    assert resumed.run(live=True)["status"] == "COMPLETE"
    assert len(proposer.calls) == len(engine.runner.calls) == 1
    assert path.read_bytes() == before


def test_paired_opt_in_keeps_random_sampling_and_seed_evidence_isolated(tmp_path):
    from failure_client.experiments.paired_discovery import (
        PairedDesign,
        PairedDiscovery,
        paired_plan,
    )
    from failure_client.methods.behavior_feedback import uniform_scene

    from .test_cause_review import cause_engine
    from .test_independent_discovery import OutcomeRobot
    from .test_paired_discovery import Proposer

    control = cause_engine(tmp_path)
    data = json.loads(
        (Path(__file__).parents[2] / "config/paired_trajectory_smoke_luna.json").read_text()
    )
    data["search"]["factor_allocation"] = "behavior-relevance-v1"
    frozen = paired_plan(
        [r["source"]["path"] for r in control.plan["history"]],
        PairedDesign.model_validate(data),
        fingerprint_fn=fingerprint,
    )
    root = PairedDiscovery.create(tmp_path / "paired", frozen, fingerprint_fn=fingerprint)
    proposer, runner = Proposer(), OutcomeRobot("PASS")
    campaign = PairedDiscovery(root, proposer=proposer, runner=runner, fingerprint_fn=fingerprint)
    result = campaign.run(live=True, max_new_attempts=8, max_new_afs_requests=2)
    assert result["status"] == "COMPLETE" and len(runner.calls) == 6
    context = proposer.calls[0]
    rel = context["exploration_allocation"]["behavior_relevance"]["object_physics"]
    ids = set(sum((v for k, v in rel.items() if k.endswith("evidence_ids")), []))
    afs_ids = {r.evidence_id for r in campaign.arm(17, "afs")._records()}
    random_ids = {r.evidence_id for r in campaign.arm(17, "random")._records()}
    assert ids <= afs_ids and not ids & random_ids
    random, ctx = campaign.arm(17, "random")._selection()
    assert ctx is None
    assert random["parameters"] == uniform_scene(
        17, "paired-random-v1", 3, schema=campaign.arm(17, "random").cfg.scene_schema
    )
