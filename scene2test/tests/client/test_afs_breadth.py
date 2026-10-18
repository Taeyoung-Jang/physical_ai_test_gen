"""Allocation and bounded two-axis contracts; synthetic, no paid inference/physics."""

import copy
import json

import pytest
from jsonschema import validate

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, accounting, selected_probe
from failure_client.methods.behavior_feedback import NoEligibleEndpoint
from failure_client.methods.breadth_policy import allocation, candidate_axes, describe, rank, reject
from llm_afs.behavior_request import request

from .test_afs_contrast import fingerprint
from .test_branch_anchors import branch_point, engine
from .test_failure_directed import proposal


def broad_engine(tmp_path, **options):
    return engine(
        tmp_path,
        taxonomy_profile="expanded-ten-v1",
        exploration_policy="breadth-v1",
        reproposal_policy="bounded-rejection-v1",
        **options,
    )


def point_for_slot(ctx):
    slot = ctx["exploration_allocation"]
    axis = slot["group_axes"][slot["required_group"]][0]
    p, anchor = branch_point(ctx, axis=axis)
    lo, hi = ctx["allowed_axes"][axis]
    if slot["required_form"] == "small":
        delta = 0.2 * (hi - lo)
        base = anchor["parameters"][axis]
        p["value"] = base + delta if base + delta <= hi else base - delta
    p["extra_changes"] = []
    paused = slot["paused_after_two_passes"]["predicted_families"]
    if p["target_family"] in paused:
        p["target_family"] = next(
            f for f in ctx["failure_objective"]["missing_supported_families"] if f not in paused
        )
    if slot["required_form"] == "combination":
        other = next(
            a for g, axes in slot["group_axes"].items() if g != slot["required_group"] for a in axes
        )
        low, high = ctx["allowed_axes"][other]
        p["extra_changes"] = [
            {
                "axis": other,
                "value": max((low, high), key=lambda v: abs(v - anchor["parameters"][other])),
            }
        ]
    return p, anchor


def attempt(axes, *, outcome="PASS", status="VALID", family="collision"):
    return {
        "candidate": {
            "axis": axes[0],
            "changed_axes": axes,
            "stage": "discovery",
            "evidence": {"target_family": family},
        },
        "episode": {"status": status, "task_outcome": outcome},
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"selection_policy": "failure-directed-v2"},
        {"taxonomy_profile": "scene-default"},
        {"reproposal_policy": "stop"},
        {"min_axis_change_fraction": 0.3},
    ],
)
def test_opt_in_is_explicit(overrides):
    with pytest.raises(ValueError):
        SearchBudget.model_validate(
            {
                "exploration_policy": "breadth-v1",
                "selection_policy": "failure-branch-v3",
                "taxonomy_profile": "expanded-ten-v1",
                "reproposal_policy": "bounded-rejection-v1",
                **overrides,
            }
        )


def test_allocator_rotates_groups_and_forms_and_charges_exclusions():
    axes = ["floor_friction", "box_mass_kg", "obstacle_1_height_m", "corridor_width_m", "human_x_m"]
    first = allocation([], axes)
    assert (first["required_group"], first["required_form"]) == ("floor_physics", "small")
    rows = [attempt(["floor_friction"], status="INCONCLUSIVE", outcome="INCONCLUSIVE")]
    second = allocation(rows, axes[1:])
    assert (second["required_group"], second["required_form"]) == ("object_physics", "large")
    rows += [attempt(["box_mass_kg"], outcome="FAIL")]
    assert allocation(rows, axes)["required_form"] == "combination"
    assert allocation(rows, axes)["required_group"] == "obstacle_geometry"


def test_combination_charges_both_axis_quotas_and_cooldown():
    axes = ["floor_friction", "box_mass_kg", "corridor_width_m"]
    rows = [attempt(axes[:2])]
    audit = accounting(rows, axes, SearchBudget())
    assert audit["axis_attempts"] == {a: int(a in axes[:2]) for a in axes}
    assert audit["selectable_axes"] == ["corridor_width_m"]
    assert allocation(rows, axes)["group_attempts"]["floor_physics"] == 1
    assert allocation(rows, axes)["group_attempts"]["object_physics"] == 1


def test_two_passes_switch_group_and_predicted_family_not_measured_labels():
    rows = [attempt(["box_mass_kg"]), attempt(["box_friction"])]
    slot = allocation(rows, ["floor_friction", "box_mass_kg"])
    assert slot["required_group"] == "floor_physics"
    assert slot["paused_after_two_passes"]["predicted_families"] == ["collision"]
    features = {"form": slot["required_form"], "groups": ["floor_physics", "layout"]}
    assert (
        reject(features, {"target_family": "collision"}, slot)
        == "repeated_pass_hypothesis_switch_required"
    )
    assert reject(features, {"target_family": "fall"}, slot) is None
    rows[-1]["episode"]["status"] = "INCONCLUSIVE"
    assert (
        allocation(rows, ["floor_friction"])["paused_after_two_passes"]["predicted_families"] == []
    )


@pytest.mark.parametrize("form", ["small", "large", "combination"])
def test_schema_and_host_execute_exact_declared_changes(tmp_path, form):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    ctx["exploration_allocation"]["required_form"] = form
    p, anchor = point_for_slot(ctx)
    raw = proposal(ctx, p)
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    schema = body["text"]["format"]["schema"]
    validate(raw, schema)
    for d in schema["$defs"].values():
        assert d["additionalProperties"] is False
        assert set(d["required"]) == set(d["properties"])
    c = selected_probe(raw, ctx, e._memory())
    changed = [k for k in c["parameters"] if c["parameters"][k] != anchor["parameters"][k]]
    assert set(changed) == set(candidate_axes(c))
    assert len(changed) == (2 if form == "combination" else 1)
    assert c["exploration"]["form"] == form
    assert c["branch_audit"]["unchanged_parameters_verified"]
    assert c["selection_audit"]["breadth_comparison"][0]["selected"]
    assert "max_output_tokens" not in body
    assert "exactly one parameter from that anchor" not in body["instructions"]


@pytest.mark.parametrize(
    "bad",
    [
        "same_axis",
        "bounds",
        "cooldown",
        "unknown_ref",
        "wrong_anchor",
        "undeclared",
        "three_changes",
    ],
)
def test_combo_retains_all_guards(tmp_path, bad):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    ctx["exploration_allocation"]["required_form"] = "combination"
    p, _ = point_for_slot(ctx)
    extra = p["extra_changes"][0]
    if bad == "same_axis":
        extra["axis"] = p["axis"]
    elif bad == "bounds":
        extra["value"] = 10000.0
    elif bad == "cooldown":
        ctx["development_search"]["selectable_axes"].remove(extra["axis"])
    elif bad == "unknown_ref":
        p["behavior_refs"] = ["invented"]
    elif bad == "wrong_anchor":
        p["anchor_case_id"] = "invented"
    elif bad == "undeclared":
        p["another_parameter"] = 0.0
    elif bad == "three_changes":
        p["extra_changes"].append({"axis": "corridor_width_m", "value": 2.0})
    with pytest.raises(ValueError):
        selected_probe(proposal(ctx, p), ctx, e._memory())


def test_mismatch_is_bounded_rejection_not_random_or_automatic_slot_change(tmp_path):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    p, _ = point_for_slot(ctx)
    p["value"] = ctx["allowed_axes"][p["axis"]][0]  # Large in a small slot.
    with pytest.raises(NoEligibleEndpoint) as exc:
        selected_probe(proposal(ctx, p), ctx, e._memory())
    assert exc.value.rejections[0]["reason"] == "allocation_form_mismatch"
    assert ctx["exploration_allocation"]["required_form"] == "small"


def test_missing_family_and_novelty_precede_proposal_order():
    obj = {
        "missing_supported_families": ["fall"],
        "intent_priority": ["challenge"],
        "target_attempt_counts": {},
    }
    slot = {"group_attempts": {"floor_physics": 0}}
    a = {
        "evidence": {"intent": "challenge", "target_family": "fall"},
        "exploration": {"groups": ["floor_physics"]},
        "novelty": 0.2,
        "space_index": 0,
    }
    c = copy.deepcopy(a)
    c.update(novelty=0.4, space_index=3)
    assert rank(c, obj, slot) > rank(a, obj, slot)
    c["evidence"]["target_family"] = "collision"
    assert rank(a, obj, slot) > rank(c, obj, slot)


def test_default_contract_still_refuses_extra_changes(tmp_path):
    e = engine(tmp_path)
    _, ctx = e._selection()
    p, _ = branch_point(ctx)
    p["extra_changes"] = []
    with pytest.raises(ValueError):
        selected_probe(proposal(ctx, p), ctx, e._memory())


def test_describe_small_large_threshold_and_individual_change_fractions():
    base = {"floor_friction": 0.8, "box_mass_kg": 2.0}
    axes = {"floor_friction": (0.05, 1.5), "box_mass_kg": (0.2, 10.0)}
    features = describe([("floor_friction", 0.8 - 0.3 * 1.45)], base, axes)
    assert features["form"] == "large"
    assert (
        describe([("floor_friction", 0.7), ("box_mass_kg", 5.0)], base, axes)["form"]
        == "combination"
    )


class SlotProposer:
    def __init__(self, reject_first=False):
        self.calls = []
        self.reject_first = reject_first

    def __call__(self, body, **kw):
        ctx = json.loads(body["input"][0]["content"])["context"]
        self.calls.append(ctx)
        p, _ = point_for_slot(ctx)
        if self.reject_first and len(self.calls) == 1:
            p["value"] = ctx["allowed_axes"][p["axis"]][0]
        raw = proposal(ctx, p)
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


@pytest.mark.parametrize("interrupt", [False, True])
def test_loop_combo_resume_and_report_without_resending_saved_response(
    tmp_path, monkeypatch, interrupt
):
    e = broad_engine(tmp_path, max_attempts=3, valid_rollout_target=3)
    proposer = SlotProposer()
    e.proposer = proposer
    e.run(live=True, max_new_attempts=2)
    if interrupt:

        def crash(_):
            raise KeyboardInterrupt()

        monkeypatch.setattr(e, "_finish_proposal", crash)
        with pytest.raises(KeyboardInterrupt):
            e.run(live=True)
        assert len(proposer.calls) == 3 and len(e.runner.calls) == 2
        e = AutonomousAFS(e.root, runner=e.runner, proposer=proposer, fingerprint_fn=fingerprint)
    result = e.run(live=True)
    assert result["status"] == "COMPLETE"
    assert len(proposer.calls) == len(e.runner.calls) == 3
    assert result["exploration_allocation"]["form_attempts"] == {
        "small": 1,
        "large": 1,
        "combination": 1,
    }
    assert result["exploration_allocation"]["next_slot_is_executable"] is False
    combo = e.state["attempts"][2]["candidate"]
    assert len(combo["changed_axes"]) == 2
    scene = e.cfg.scene(e.runner.calls[2]).model_dump()
    assert all(scene[a] == combo["parameters"][a] for a in combo["changed_axes"])
    text = e.report().read_text()
    assert "combination" in text and "changed_axes" in text
    e.run(live=True)
    assert len(proposer.calls) == 3  # Completed target never spends remaining slots.


def test_allocation_reproposal_charges_request_without_switching_slot(tmp_path):
    e = broad_engine(tmp_path)
    proposer = SlotProposer(reject_first=True)
    e.proposer = proposer
    result = e.run(live=True, max_new_attempts=1)
    assert result["afs_requests_attempted"] == 2 and result["attempted"] == 1
    assert result["afs_proposals_rejected"] == 1
    assert (
        proposer.calls[0]["exploration_allocation"] == proposer.calls[1]["exploration_allocation"]
    )
    reason = proposer.calls[1]["proposal_feedback"]["rejected_proposals"][0]["endpoints"][0][
        "reason"
    ]
    assert reason == "allocation_form_mismatch"


@pytest.mark.parametrize("bad", ["tiny_second", "same_group", "duplicate_scene"])
def test_combination_guard_checks_second_axis_and_full_scene(tmp_path, bad):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    ctx["exploration_allocation"]["required_form"] = "combination"
    memory = e._memory()
    p, anchor = point_for_slot(ctx)
    extra = p["extra_changes"][0]
    if bad == "tiny_second":
        extra["value"] = anchor["parameters"][extra["axis"]] + 0.0001
    elif bad == "same_group":
        # Both object-physics axes are distinct but not a cross-group combination.
        ctx["exploration_allocation"]["required_group"] = "object_physics"
        p["axis"], p["value"] = "box_mass_kg", 10.0
        extra.update(axis="box_friction", value=0.05)
    else:
        old = copy.deepcopy(next(c for c in memory["cases"] if c["case_id"] == anchor["case_id"]))
        old["case_id"] = "already-observed-combination"
        old["parameters"].update({p["axis"]: p["value"], extra["axis"]: extra["value"]})
        memory["cases"].append(old)
    with pytest.raises(NoEligibleEndpoint) as exc:
        selected_probe(proposal(ctx, p), ctx, memory)
    assert (
        exc.value.rejections[0]["reason"]
        == {
            "tiny_second": "discovery_step_too_small",
            "same_group": "combination_requires_two_factor_groups",
            "duplicate_scene": "already_observed",
        }[bad]
    )
