"""Ten-family rules are synthetic diagnostic checks, not new robot experiments."""

import json
import runpy

import pytest

from failure_client.evaluation.behavior_measures import BehaviorInterval, EvidenceRef
from failure_client.evaluation.expanded_taxonomy import (
    RULES,
    classify_expanded,
    new_observations,
)
from failure_client.evaluation.failure_taxonomy import classify_record
from failure_client.evaluation.research_records import EXPANDED_FAMILIES, Attribution
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics

from .test_discovery_measures import episode, load
from .test_usage_taxonomy import dense_archive


def states(*, height=0.75):
    return [{"time_s": n / 10, "qpos": [3, 0, height, 1, 0, 0, 0]} for n in range(61)]


def progress(**changes):
    return {
        "distance_m": 0.2,
        "radius_m": 0.25,
        "inside_goal_region": True,
        "required_dwell_s": 1.0,
        "current_dwell_s": 0.65,
        "goal_reached": False,
        **changes,
    }


GOAL = {"radius_m": 0.25, "dwell_s": 1.0}


def action(name="move", **details):
    return BehaviorInterval(
        kind="action_window",
        start_s=0.0,
        end_s=6.0,
        timing="observation_window",
        evidence=[EvidenceRef(artifact="decisions.jsonl", sha256="verified")],
        details={
            "action": name,
            "execution": "accepted",
            "tool_status": "executed",
            "execution_start_s": 3.0,
            "motion_elapsed_s": 3.0,
            "motion_net_translation_m": 0.01,
            "vx_mps": 0.2,
            "vy_mps": 0.0,
            "yaw_rate_rps": 0.0,
            **details,
        },
    )


def observations(rows=None, actions=(), result=None, **kwargs):
    return new_observations(
        states() if rows is None else rows, actions, result or {}, GOAL, **kwargs
    )


def test_fall_requires_sustained_sampled_pose_and_complete_trace():
    found, _ = observations(states(height=0.3))
    assert found["fall"] == "DETECTED"
    rows = states()
    rows[1]["qpos"][2] = 0.3
    assert observations(rows)[0]["fall"] == "NOT_DETECTED"
    assert observations(rows[::10])[0]["fall"] == "UNKNOWN"


def test_goal_completion_is_narrow_not_all_budget_failures():
    assert (
        observations(result={"goal_progress": progress()})[0]["goal_completion_failure"]
        == "DETECTED"
    )
    outside = progress(distance_m=0.5, inside_goal_region=False, current_dwell_s=0.0)
    assert (
        observations(result={"goal_progress": outside})[0]["goal_completion_failure"]
        == "NOT_DETECTED"
    )
    assert (
        observations(result={"reason": "BUDGET_EXHAUSTED"})[0]["goal_completion_failure"]
        == "UNKNOWN"
    )
    bad = progress(required_dwell_s=0.5)
    assert observations(result={"goal_progress": bad})[0]["goal_completion_failure"] == "UNKNOWN"


def test_stall_uses_execution_motion_not_inference_hold_or_intentional_stop():
    assert observations(actions=[action()])[0]["locomotion_stall"] == "DETECTED"
    for a in [
        action(motion_elapsed_s=0.2),
        action(vx_mps=0.0),
        action(motion_net_translation_m=0.3),
        action(tool_status="target_reached"),
    ]:
        assert observations(actions=[a])[0]["locomotion_stall"] == "NOT_DETECTED"
    assert observations(actions=[action(motion_elapsed_s=None)])[0]["locomotion_stall"] == "UNKNOWN"
    rows = states()
    rows[40]["qpos"][0] = 4
    assert observations(rows, actions=[action()])[0]["locomotion_stall"] == "NOT_DETECTED"


def test_manipulation_rejection_is_diagnostic_and_later_success_supersedes_it():
    rejected = action(
        "push_object", object_id="box", tool_status="rejected", tool_reason="unsupported_box_face"
    )
    success = action("push_object", object_id="box", tool_status="success")
    assert observations(actions=[rejected])[0]["manipulation_failure"] == "DETECTED"
    assert observations(actions=[rejected, success])[0]["manipulation_failure"] == "NOT_DETECTED"
    assert (
        observations(actions=[rejected], actions_available=False)[0]["manipulation_failure"]
        == "UNKNOWN"
    )


def test_ten_inventory_explicit_and_legacy_six_unchanged():
    r = episode(
        0,
        attribution=Attribution(
            primary_family="goal_completion_failure",
            rule_version=RULES["goal_completion_failure"],
            evidence_refs=["events.jsonl"],
        ),
    )
    with pytest.raises(ValueError, match="registry"):
        calculate_discovery_metrics([r], family_rules=RULES)
    metrics = calculate_discovery_metrics(
        [r], family_rules=RULES, family_inventory=EXPANDED_FAMILIES
    )
    assert metrics["targets"]["family_denominator"] == 10
    group = metrics["groups"][0]
    assert group["discovered_family_count"] == 1
    assert group["observed_family_coverage_lower_bound"] == 0.1
    assert calculate_discovery_metrics([episode(1)])["targets"]["family_denominator"] == 6


@pytest.mark.parametrize("outcome", ["PASS", "FAIL"])
def test_archive_source_and_goal_outcome_preserved(tmp_path, outcome):
    root = dense_archive(tmp_path / "archive", outcome=outcome)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    r = load(root)
    old = classify_record(r)
    expanded = classify_expanded(r)
    assert expanded.task_outcome == old.task_outcome == outcome
    assert expanded.status == old.status
    assert len(expanded.taxonomy["families"]) == 10
    if outcome == "PASS":
        assert expanded.attribution is None
        assert all(
            expanded.taxonomy["families"][f]["status"] == "N/A" for f in EXPANDED_FAMILIES[6:]
        )
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_exclusion_never_becomes_failure_type(tmp_path):
    root = dense_archive(tmp_path / "archive")
    (root / "states.jsonl").unlink()
    expanded = classify_expanded(load(root))
    assert expanded.task_outcome == "INCONCLUSIVE" and expanded.attribution is None
    assert all(
        expanded.taxonomy["families"][f]["status"] == "UNKNOWN" for f in EXPANDED_FAMILIES[6:]
    )


def test_multiple_findings_count_one_primary_not_many(tmp_path, monkeypatch):
    import failure_client.evaluation.expanded_taxonomy as expanded_module

    root = dense_archive(tmp_path / "archive")
    monkeypatch.setattr(
        expanded_module,
        "new_observations",
        lambda *a, **kw: ({f: "DETECTED" for f in EXPANDED_FAMILIES[6:]}, {}),
    )
    record = classify_expanded(load(root))
    assert len(record.taxonomy["diagnostic_families"]) == 4
    assert record.attribution.primary_family == "fall"
    metrics = calculate_discovery_metrics(
        [record],
        family_rules=RULES,
        family_inventory=EXPANDED_FAMILIES,
    )
    assert metrics["groups"][0]["discovered_family_count"] == 1


def test_existing_unique_primary_and_old_rules_are_preserved(tmp_path, monkeypatch):
    import failure_client.evaluation.expanded_taxonomy as expanded_module

    root = dense_archive(tmp_path / "archive", collision=True)
    legacy = classify_record(load(root))
    assert legacy.attribution.primary_family == "collision"
    monkeypatch.setattr(
        expanded_module,
        "new_observations",
        lambda *a, **kw: ({f: "DETECTED" for f in EXPANDED_FAMILIES[6:]}, {}),
    )
    record = classify_expanded(load(root))
    assert record.attribution.primary_family == "collision"


def test_reanalysis_exports_separate_report_with_old_metrics(tmp_path):
    tool = runpy.run_path("tools/reanalyze_failure_types.py")
    root = dense_archive(tmp_path / "archive")
    report, metrics = tool["analyze"]([root], tmp_path / "output")
    assert "4/10" in report.read_text()
    assert (
        metrics["analysis_scope"]["legacy_six_family_metrics"]["targets"]["family_denominator"] == 6
    )
    assert (
        json.loads((report.parent / "metrics.json").read_text())["targets"]["family_denominator"]
        == 10
    )
    with pytest.raises(FileExistsError):
        tool["analyze"]([root], report.parent)
    with pytest.raises(ValueError, match="separate"):
        tool["analyze"]([root], root / "output")
