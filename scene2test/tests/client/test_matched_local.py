"""Fixed-base 1/2-axis comparison, synthetic archives and mock proposer only."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from failure_client.experiments.paired_discovery import PairedDesign, PairedDiscovery, paired_plan
from failure_client.methods.autonomous_feedback import selected_probe
from failure_client.methods.behavior_feedback import parameters
from failure_client.methods.matched_local import (
    VERSION,
    check_candidate,
    random_candidate,
    validate_design,
)
from llm_afs.behavior_request import request

from .test_afs_contrast import fingerprint
from .test_branch_anchors import branch_point
from .test_cause_review import cause_engine, reviewed_raw
from .test_independent_discovery import OutcomeRobot


class LocalProposer:
    def __init__(self):
        self.calls = []

    def __call__(self, body, **_):
        ctx = json.loads(body["input"][0]["content"])["context"]
        self.calls.append(ctx)
        count = ctx["matched_local"]["required_change_count"]
        axes = sorted(
            ctx["allowed_axes"], key=lambda a: ctx["development_search"]["axis_attempts"][a]
        )
        point, anchor = branch_point(ctx, axis=axes[0], intent="mechanism_transfer")
        changes = []
        for axis in axes[:count]:
            lo, hi = ctx["allowed_axes"][axis]
            base = anchor["parameters"][axis]
            delta = (0.15 + len(self.calls) * 0.01) * (hi - lo)
            changes.append((axis, base + delta if base + delta <= hi else base - delta))
        point.update(
            value=changes[0][1], extra_changes=[{"axis": a, "value": v} for a, v in changes[1:]]
        )
        raw = reviewed_raw(ctx, point)
        raw["spaces"][0]["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
        validate(raw, body["text"]["format"]["schema"])
        return {
            "status": "completed",
            "service_tier": "default",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 10, "output_tokens": 10},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        }


def setup_local(tmp_path, *, outcome="PASS", history_limit=4, seeds=None):
    control = cause_engine(tmp_path)
    data = json.loads(
        (Path(__file__).parents[2] / "config/paired_trajectory_smoke_luna.json").read_text()
    )
    cfg = control.cfg
    base = parameters(control._memory()["cases"][0])
    data.update(
        seeds=seeds or [17],
        cold_start_per_arm=1,
        valid_per_arm=5,
        attempts_per_arm=6,
        afs_requests_per_seed=5,
    )
    data["search"].update(
        valid_rollout_target=5, max_attempts=6, max_afs_requests=5, history_limit=history_limit
    )
    data["scene_domain"] = {
        "schema_version": "bounded-scene-domain-v1",
        "scene_schema": cfg.scene_schema,
        "scope": "Synthetic local comparison checks",
        "axes": cfg.design()["axes"],
    }
    data["matched_local"] = {
        "schema_version": VERSION,
        "base_parameters": base,
        "change_counts": [1, 2],
    }
    design = PairedDesign.model_validate(data)
    frozen = paired_plan(
        [r["source"]["path"] for r in control.plan["history"]], design, fingerprint_fn=fingerprint
    )
    root = PairedDiscovery.create(tmp_path / "local", frozen, fingerprint_fn=fingerprint)
    proposer, robot = LocalProposer(), OutcomeRobot(outcome)
    return (
        PairedDiscovery(root, runner=robot, proposer=proposer, fingerprint_fn=fingerprint),
        proposer,
        robot,
    )


def test_random_resets_base_and_changes_exact_alternating_count(tmp_path):
    e, _, _ = setup_local(tmp_path)
    spec, domain = e.design.matched_local, e.design.scene_domain
    for i in range(20):
        a = random_candidate(spec, domain, 0.1, 17, i)
        assert a == random_candidate(spec, domain, 0.1, 17, i)
        changed = check_candidate(a["parameters"], spec, domain, 1 + i % 2, 0.1)
        assert set(changed) == set(a["changed_axes"])
        assert all(
            a["parameters"][axis] == base
            for axis, base in spec["base_parameters"].items()
            if axis not in changed
        )


def test_frozen_base_domain_and_change_schedule_cannot_be_widened(tmp_path):
    e, _, _ = setup_local(tmp_path)
    spec = copy.deepcopy(e.design.matched_local)
    for counts in ([2, 1], [True, 2], [1.0, 2.0], [1, 2, 1]):
        spec["change_counts"] = counts
        with pytest.raises(ValueError, match="alternating"):
            validate_design(spec, e.design.scene_domain, 0.1)
    spec = copy.deepcopy(e.design.matched_local)
    axis = next(iter(spec["base_parameters"]))
    spec["base_parameters"][axis] = 100000
    with pytest.raises(ValueError, match="outside"):
        validate_design(spec, e.design.scene_domain, 0.1)
    frozen = copy.deepcopy(e.wrapped)
    frozen["manifest"]["matched_local"]["base_parameters"][axis] = 1.0
    from failure_client.experiments.paired_discovery import checked_manifest
    from llm_afs.behavior import digest

    frozen["sha256"] = digest(frozen["manifest"])
    with pytest.raises(ValueError, match="matched-local"):
        checked_manifest(frozen)


def test_both_methods_share_base_and_count_and_only_own_history(tmp_path):
    e, p, r = setup_local(tmp_path, history_limit=2)
    s = e.run(live=True, max_new_attempts=12, max_new_afs_requests=5)
    assert s["status"] == "COMPLETE" and s["evaluation_complete"]
    assert len(r.calls) == 10 and len(p.calls) == 4
    assert s["baseline_check"]["status"] == "pass"
    assert all(
        row["counts"]["1"]["valid"] == row["counts"]["2"]["valid"] == 2
        for row in s["matched_change_counts"]
    )
    assert r.calls[0] == r.calls[1] == e.design.matched_local["base_parameters"]
    for method in ["afs", "random"]:
        arm = e.arm(17, method)
        for i, a in enumerate(arm.state["attempts"][1:]):
            check_candidate(
                a["candidate"]["parameters"],
                e.design.matched_local,
                e.design.scene_domain,
                1 + i % 2,
                0.1,
            )
    random_ids = {r.evidence_id for r in e.arm(17, "random")._records()}
    for ctx in p.calls:
        assert len(ctx["anchor_catalog"]) == 1
        assert ctx["anchor_catalog"][0]["parameters"] == e.design.matched_local["base_parameters"]
        assert not random_ids & {row["id"] for row in ctx["latest"]["evidence"]}
        assert ctx["development_search"]["external_history"] is False
        assert set(ctx["development_search"]["selectable_axes"]) == set(ctx["allowed_axes"])
    before = len(p.calls), len(r.calls)
    e.run(live=True, max_new_attempts=12)
    assert before == (len(p.calls), len(r.calls))
    report = e.report()
    assert "matched-local-v1" in report.read_text()


def test_random_does_not_use_previous_outcome_or_scene(tmp_path):
    e, _, _ = setup_local(tmp_path)
    e.run(live=True, max_new_attempts=2)
    arm = e.arm(17, "random")
    original = arm._selection()
    arm.state["attempts"][0]["episode"]["task_outcome"] = "FAIL"
    arm.state["attempts"][0]["candidate"]["parameters"] = {}
    assert arm._selection() == original


def test_failed_baseline_stops_before_any_proposal(tmp_path):
    e, p, r = setup_local(tmp_path, outcome="FAIL")
    s = e.run(live=True, max_new_attempts=12)
    assert s["status"] == "BASELINE_NOT_CONFIRMED"
    assert s["baseline_check"]["status"] == "not_confirmed"
    assert not p.calls and len(r.calls) == 1
    e.run(live=True, max_new_attempts=12)
    assert len(r.calls) == 1


def test_schema_and_host_enforce_count_in_every_candidate(tmp_path):
    e, _, _ = setup_local(tmp_path)
    e.run(live=True, max_new_attempts=2)
    arm = e.arm(17, "afs")
    _, ctx = arm._selection()
    body = request(ctx, "synthetic", selection_policy=arm.request_policy)
    raw_response = LocalProposer()(body)
    from llm_afs.provider import extract_proposal

    raw = extract_proposal(raw_response)
    invalid = copy.deepcopy(raw["spaces"][0])
    axis = next(a for a in ctx["allowed_axes"] if a != invalid["axis"])
    base = ctx["matched_local"]["base_parameters"][axis]
    lo, hi = ctx["allowed_axes"][axis]
    invalid["extra_changes"] = [{"axis": axis, "value": lo if base != lo else hi}]
    raw["spaces"].append(invalid)
    with pytest.raises(ValidationError):
        validate(raw, body["text"]["format"]["schema"])
    with pytest.raises(ValueError, match="change count"):
        selected_probe(raw, ctx, arm._memory())


def test_saved_response_resume_keeps_fixed_contract_and_no_resend(tmp_path, monkeypatch):
    e, p, r = setup_local(tmp_path)
    e.run(live=True, max_new_attempts=2)
    from failure_client.experiments.paired_discovery import PairedArm

    original = PairedArm._finish_proposal

    def crash(self, row):
        raise RuntimeError("after saved response")

    monkeypatch.setattr(PairedArm, "_finish_proposal", crash)
    with pytest.raises(RuntimeError, match="after saved response"):
        e.run(live=True)
    assert len(p.calls) == 1 and len(r.calls) == 2
    monkeypatch.setattr(PairedArm, "_finish_proposal", original)
    e.run(live=True, max_new_attempts=1)
    assert len(p.calls) == 1 and len(r.calls) == 2
    e.run(live=True, max_new_attempts=1)
    assert len(p.calls) == 1 and len(r.calls) == 3
