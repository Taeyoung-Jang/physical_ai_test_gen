"""Pure feedback and mock resume tests; no API/robot/physics."""

import json
from copy import deepcopy

import pytest
from jsonschema import validate

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from failure_client.methods.trajectory_feedback import feedback, prediction_check, trajectory
from llm_afs.behavior import digest
from llm_afs.behavior_request import request

from .test_action_search_feedback import entry
from .test_afs_breadth import broad_engine, point_for_slot
from .test_afs_contrast import fingerprint
from .test_cause_review import reviewed_raw
from .test_discovery_continuation import TransferProposer

GOAL = {"target_xy_m": [7, 0], "radius_m": 0.25, "dwell_s": 1}


def observed(ref="e", **kwargs):
    e = entry(
        {"action": "navigate_to", "target_xy_m": [7, 0], "tool_status": "blocked_endpoint"},
        {
            "action": "navigate_to",
            "tool_status": "execution_slice_ended",
            "motion_goal_distance_reduction_m": 1.1,
        },
        {"action": "navigate_to", "target_xy_m": [7, 0], "tool_status": "blocked_endpoint"},
        {"action": "move", "tool_status": "executed", "goal_distance_m": 0.49},
    )
    e["record"].update(
        evidence_id=ref,
        status="VALID",
        task_outcome="FAIL",
        condition_id="condition10",
        termination_reason="BUDGET_EXHAUSTED",
        policy_origin="openai_api",
        scene_id=ref,
        taxonomy={
            "families": {"collision": {"status": "NOT_DETECTED"}},
            "measurements": {"blocked_tools": [], "terminal_progress": {"stalled": False}},
        },
    )
    e["record"].update(kwargs)
    return e


def memory(*entries):
    return {
        "episodes": {e["record"]["evidence_id"]: e for e in entries},
        "cases": [
            {
                "episodes": [e["record"]["evidence_id"]],
                "task_contract": {
                    "goal": GOAL,
                    "episode_budget": {
                        "max_robot_policy_calls": 15
                        if e["record"]["condition_id"] == "condition15"
                        else 10
                    },
                },
            }
            for e in entries
        ],
    }


def attempt(e, family="collision", n=0):
    return {
        "id": f"attempt{n}",
        "candidate": {"evidence": {"target_family": family}},
        "episode": e["record"],
    }


def test_goal_block_progress_sequence_preserves_unclassified_fail():
    e = observed()
    before = deepcopy(e)
    d = trajectory(e, GOAL)
    assert d["patterns"]["blocked_goal_then_progress_budget_fail"]
    assert d["observed_goal_endpoint_blocks"] == 2
    assert d["repeated_blocked_endpoints"] == [{"target_xy_m": [7, 0], "count": 2}]
    assert d["outcome"] == "FAIL" and d["primary_family"] is None
    assert e == before


def test_progress_before_block_is_not_block_then_progress():
    e = observed()
    e["behavior"]["intervals"] = list(reversed(e["behavior"]["intervals"][:2]))
    assert trajectory(e, GOAL)["patterns"]["blocked_goal_then_progress_budget_fail"] is False


def test_tiny_gait_progress_not_meaningful_route_progress():
    e = observed()
    e["behavior"]["intervals"][1]["details"]["motion_goal_distance_reduction_m"] = 0.001
    assert trajectory(e, GOAL)["patterns"]["blocked_goal_then_progress_budget_fail"] is False


@pytest.mark.parametrize("kind", ["missing", "partial", "empty"])
def test_no_unknown_absence_as_zero(kind):
    e = observed()
    if kind == "missing":
        e["behavior"]["components"]["actions"] = "UNAVAILABLE"
    elif kind == "partial":
        e["behavior"]["intervals"][0]["censored"] = True
    else:
        e["behavior"]["intervals"] = []
    d = trajectory(e, GOAL)
    assert not d["action_results_complete"]
    assert d["patterns"]["no_manipulation_request"] is None


def test_rejected_push_not_physical_incapacity_and_entry_exit_not_new_type():
    e = observed()
    extra = entry(
        {"action": "push_object", "tool_status": "rejected", "tool_reason": "unsupported_box_face"},
        {
            "action": "move",
            "tool_status": "executed",
            "goal_distance_m": 0.248,
            "goal_current_dwell_s": 0.19,
        },
        {"action": "observe", "tool_status": "executed", "goal_distance_m": 0.26},
    )
    e["behavior"] = extra["behavior"]
    e["record"]["taxonomy"]["measurements"]["expanded_behavior"] = {
        "goal_completion_failure": {"distance_m": 0.26, "current_dwell_s": 0}
    }
    d = trajectory(e, GOAL)
    assert d["patterns"]["manipulation_tool_rejected"]
    assert d["patterns"]["entered_goal_then_finished_outside"]
    assert d["goal_entry_dwell_s"] == [0.19]
    assert d["primary_family"] is None


def test_locally_rejected_manipulation_is_still_an_observed_request():
    e = observed()
    e["behavior"] = entry({"action": "push_object", "execution": "rejected"})["behavior"]
    d = trajectory(e, GOAL)
    assert d["patterns"]["no_manipulation_request"] is False
    assert d["manipulation_results"][0]["execution"] == "rejected"


def test_prediction_uses_detector_not_invented_cause_or_family():
    e = observed()
    c = prediction_check(attempt(e), e)
    assert c["predicted_detector_status"] == "NOT_DETECTED"
    assert c["observed_primary_family"] is None and c["observed_goal_outcome"] == "FAIL"
    assert c["gate_observations"]["recent_blocked_count"] == 0
    e["record"]["taxonomy"] = {}
    assert prediction_check(attempt(e), e)["predicted_detector_status"] == "UNKNOWN"


def test_cumulative_memory_beyond_history_and_separate_budgets_and_exclusions():
    entries = [observed(str(i)) for i in range(6)]
    diagnostic = observed("diagnostic", condition_id="condition15")
    excluded = observed("excluded", status="INCONCLUSIVE", task_outcome="INCONCLUSIVE")
    mem = memory(*entries, diagnostic, excluded)
    before = deepcopy(mem)
    f = feedback(mem, [attempt(e, n=i) for i, e in enumerate(entries)], ["5"])
    assert len(f["presented_episode_summaries"]) == 1
    current = next(g for g in f["condition_groups"] if g["scope"] == "current")
    assert current["failures"] == 6
    assert current["pattern_counts"]["blocked_goal_then_progress_budget_fail"] == 6
    assert len(current["representatives"]["blocked_goal_then_progress_budget_fail"]) == 2
    assert len(f["recent_prediction_checks"]) == 4
    historical = next(g for g in f["condition_groups"] if g["scope"] == "historical")
    assert historical["condition_id"] == "condition15" and historical["failures"] == 1
    assert len(f["condition_groups"]) == 2 and mem == before


def test_pass_not_counted_as_failed_pattern_and_deterministic():
    e = observed(task_outcome="PASS")
    f = feedback(memory(e), [attempt(e)], ["e"])
    assert f == feedback(memory(e), [attempt(e)], ["e"])
    assert f["condition_groups"][0]["failures"] == 0
    assert not f["condition_groups"][0]["pattern_counts"]


def test_schema_and_host_unchanged_with_new_feedback_opt_in(tmp_path):
    engine = broad_engine(
        tmp_path, feedback_policy="cause-review-v3", pattern_feedback="trajectory-v1"
    )
    _, ctx = engine._selection()
    assert "trajectory_feedback" in ctx["failure_objective"]
    p, anchor = point_for_slot(ctx)
    raw = reviewed_raw(ctx, p)
    raw["spaces"][0]["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
    new = request(ctx, "gpt-6-luna", selection_policy="autonomous_development_endpoint")
    old_ctx = deepcopy(ctx)
    del old_ctx["failure_objective"]["trajectory_feedback"]
    old = request(old_ctx, "gpt-6-luna", selection_policy="autonomous_development_endpoint")
    old_schema = deepcopy(old["text"]["format"]["schema"])
    new_schema = deepcopy(new["text"]["format"]["schema"])
    for schema in (old_schema, new_schema):
        del schema["properties"]["context_sha256"]["enum"]
    assert old_schema == new_schema
    assert "trajectory_feedback before" in new["instructions"]
    validate(raw, new["text"]["format"]["schema"])
    chosen = selected_probe(raw, ctx, engine._memory())
    old_raw = {**raw, "context_sha256": digest(old_ctx)}
    assert chosen["parameters"] == selected_probe(old_raw, old_ctx, engine._memory())["parameters"]


def test_opt_in_requires_reviewed_mode_and_default_off(tmp_path):
    assert SearchBudget().pattern_feedback == "off"
    with pytest.raises(ValueError, match="requires cause-review-v3"):
        SearchBudget(pattern_feedback="trajectory-v1")
    e = broad_engine(tmp_path, feedback_policy="cause-review-v3")
    _, ctx = e._selection()
    assert "trajectory_feedback" not in ctx["failure_objective"]


def test_same_condition_different_task_budget_stays_separate():
    e, d = observed("a"), observed("b")
    mem = memory(e, d)
    mem["cases"][1]["task_contract"]["episode_budget"]["max_robot_policy_calls"] = 15
    f = feedback(mem, [attempt(e), attempt(d, n=1)], ["a", "b"])
    assert len(f["condition_groups"]) == len(f["prediction_status_counts"]) == 2


def test_saved_response_resumes_without_extra_call_and_audits_feedback(tmp_path, monkeypatch):
    e = broad_engine(
        tmp_path,
        feedback_policy="cause-review-v3",
        anchor_policy="failure-diversity-v4",
        pattern_feedback="trajectory-v1",
        max_attempts=1,
        valid_rollout_target=1,
    )
    p = TransferProposer()
    e.proposer = p

    def interrupted(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(e, "_finish_proposal", interrupted)
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    assert len(p.calls) == 1 and not e.runner.calls
    # A saved request remains byte-identical across reconstruction and collection.
    path = e.root / "proposals/proposal_00000/request.json"
    before = path.read_bytes()
    r = AutonomousAFS(e.root, runner=e.runner, proposer=p, fingerprint_fn=fingerprint)
    assert r.run(live=True)["status"] == "COMPLETE"
    assert len(p.calls) == len(e.runner.calls) == 1
    assert path.read_bytes() == before
    audit = r.state["attempts"][0]["candidate"]["selection_audit"]
    assert audit["trajectory_feedback"]["version"] == "trajectory-feedback-v1"
    assert "trajectory_feedback" in r.report().read_text()
    assert json.loads(before)["model"] == "gpt-6-luna"
