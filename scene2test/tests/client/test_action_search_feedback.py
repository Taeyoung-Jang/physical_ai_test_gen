"""Search-only diagnostic and new-set coverage contracts; no network or simulator."""

import copy

import pytest

from failure_client.methods.action_diagnostics import action_diagnostics
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from failure_client.methods.failure_objective import failure_objective
from llm_afs.behavior_request import request

from .test_branch_anchors import branch_point, engine
from .test_failure_directed import proposal


def entry(*details, available=True):
    return {
        "record": {"measures": {"last_sample_goal_distance_m": 0.4}},
        "behavior": {
            "components": {"actions": "AVAILABLE" if available else "UNAVAILABLE"},
            "intervals": [
                {
                    "kind": "action_window",
                    "censored": False,
                    "details": {"execution": "accepted", "observation_version": n, **d},
                    "evidence": [{"artifact": "decisions.jsonl", "first_line": n + 1}],
                }
                for n, d in enumerate(details)
            ],
        },
    }


def test_whole_sequence_reports_blocked_repeats_and_staging_not_new_labels():
    blocked = {"action": "navigate_to", "tool_status": "blocked_endpoint", "target_xy_m": [7, 0]}
    e = entry(
        blocked,
        {"action": "navigate_to", "tool_status": "execution_slice_ended"},
        blocked,
        {"action": "navigate_to", "tool_status": "target_reached", "goal_distance_m": 0.41},
    )
    before = copy.deepcopy(e)
    d = action_diagnostics(e, {"radius_m": 0.25})
    assert d["blocked_navigation_count"] == 2
    assert d["first_blocked_navigation"]["observation_version"] == 0
    assert d["repeated_blocked_endpoints"] == [{"target_xy_m": [7, 0], "count": 2}]
    assert len(d["staging_arrivals_outside_goal"]) == 1
    assert d["manipulation_engagement"] == "NO_TOOL_REQUEST_OBSERVED"
    assert "primary_family" not in d and "task_outcome" not in d
    assert e == before


def test_missing_and_censored_data_do_not_mean_no_manipulation():
    d = action_diagnostics(entry(available=False), {})
    assert d["status"] == "UNAVAILABLE"
    assert "blocked_navigation_count" not in d
    partial = entry({"action": "navigate_to", "tool_status": "blocked_endpoint"})
    partial["behavior"]["intervals"][0]["censored"] = True
    d = action_diagnostics(partial, {})
    assert d["blocked_navigation_count"] == 0
    assert not d["complete_action_results"]
    assert d["manipulation_engagement"] == "UNKNOWN_PARTIAL_RESULTS"


def test_push_request_not_physical_success_and_rejected_navigation_not_blockage():
    e = entry(
        {"action": "push_object", "execution": "rejected", "tool_success": False},
        {"action": "navigate_to", "execution": "rejected", "tool_status": "blocked_endpoint"},
    )
    d = action_diagnostics(e, {})
    assert d["manipulation_engagement"] == "TOOL_REQUEST_OBSERVED_NOT_PHYSICAL_SUCCESS"
    assert d["blocked_navigation_count"] == 0


@pytest.mark.parametrize("kwargs", [{}, {"selection_policy": "failure-branch-v3"}])
def test_diagnostics_require_explicit_expanded_branch(kwargs):
    with pytest.raises(ValueError, match="explicit expanded branch"):
        SearchBudget(feedback_policy="action-diagnostics-v1", **kwargs)


def detected_completion(monkeypatch):
    import failure_client.evaluation.expanded_taxonomy as taxonomy

    monkeypatch.setattr(
        taxonomy,
        "new_observations",
        lambda *a, **kw: (
            {
                "fall": "NOT_DETECTED",
                "locomotion_stall": "NOT_DETECTED",
                "manipulation_failure": "NOT_DETECTED",
                "goal_completion_failure": "DETECTED",
            },
            {},
        ),
    )


def test_imported_family_remains_missing_in_new_set_and_request_explains_scope(
    tmp_path, monkeypatch
):
    detected_completion(monkeypatch)
    e = engine(
        tmp_path, taxonomy_profile="expanded-ten-v1", feedback_policy="action-diagnostics-v1"
    )
    _, ctx = e._selection()
    o = ctx["failure_objective"]
    assert o["historical_discovered_families"] == ["goal_completion_failure"]
    assert o["current_discovered_families"] == []
    assert "goal_completion_failure" in o["missing_supported_families"]
    assert all("action_diagnostics" in r for r in o["behavior_observations"])
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    assert "across NEW session attempts only" in body["instructions"]
    assert "max_output_tokens" not in body
    # Existing ranking now reads new-set missing families, rather than the cumulative union.
    p, _ = branch_point(ctx, axis="floor_friction")
    q, _ = branch_point(ctx, axis="box_mass_kg")
    p["target_family"], q["target_family"] = "goal_completion_failure", "fall"
    ctx["failure_objective"]["target_attempt_counts"]["fall"] = 1
    assert (
        selected_probe(proposal(ctx, p, q), ctx, e._memory())["evidence"]["target_family"]
        == "goal_completion_failure"
    )


def test_current_coverage_uses_measured_valid_fail_not_prediction_or_pass(tmp_path, monkeypatch):
    detected_completion(monkeypatch)
    e = engine(
        tmp_path, taxonomy_profile="expanded-ten-v1", feedback_policy="action-diagnostics-v1"
    )
    memory = e._memory()
    rows = list(memory["episodes"].values())
    failed = next(r["record"] for r in rows if r["record"]["task_outcome"] == "FAIL")
    passed = next(r["record"] for r in rows if r["record"]["task_outcome"] == "PASS")
    memory["episodes"][failed["evidence_id"]]["behavior"] = entry(
        {"action": "navigate_to", "tool_status": "blocked_endpoint", "target_xy_m": [7, 0]}
    )["behavior"]

    def objective(records):
        return failure_objective(
            memory,
            [
                {"id": str(n), "candidate": {"evidence": {"target_family": "fall"}}, "episode": r}
                for n, r in enumerate(records)
            ],
            e.cfg.scene_schema,
            [],
            taxonomy_profile="expanded-ten-v1",
            feedback_policy="action-diagnostics-v1",
        )

    pass_only = objective([passed])
    assert pass_only["current_discovered_families"] == []
    assert pass_only["action_pattern_feedback"]["current_failure_episode_counts"] == {}
    assert (
        pass_only["action_pattern_feedback"]["historical_failure_episode_counts"][
            "failed_with_blocked_navigation"
        ]
        == 1
    )
    o = objective([failed, failed])
    assert o["current_discovered_families"] == ["goal_completion_failure"]
    assert "goal_completion_failure" not in o["missing_supported_families"]
    assert "fall" in o["missing_supported_families"]
    assert o["recent_hypothesis_results"][0]["predicted_family"] == "fall"
    assert "action_diagnostics" in o["recent_hypothesis_results"][0]
    assert (
        o["action_pattern_feedback"]["current_failure_episode_counts"][
            "failed_with_blocked_navigation"
        ]
        == 1
    )  # Duplicate ledger references do not double-count an episode.


def test_legacy_context_has_no_new_diagnostics_or_coverage_scope(tmp_path):
    e = engine(tmp_path, taxonomy_profile="expanded-ten-v1")
    _, ctx = e._selection()
    assert "feedback_policy" not in ctx["failure_objective"]
    assert all(
        "action_diagnostics" not in r for r in ctx["failure_objective"]["behavior_observations"]
    )
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    assert "across NEW session attempts only" not in body["instructions"]


def test_new_feedback_survives_saved_response_resume_without_resend(tmp_path, monkeypatch):
    from failure_client.experiments.afs_autonomous import AutonomousAFS

    from .test_afs_breadth import SlotProposer, broad_engine
    from .test_afs_contrast import fingerprint

    e = broad_engine(
        tmp_path,
        feedback_policy="action-diagnostics-v1",
        max_attempts=3,
        valid_rollout_target=3,
    )
    proposer = SlotProposer()
    e.proposer = proposer
    e.run(live=True, max_new_attempts=1)

    def crash(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(e, "_finish_proposal", crash)
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    assert len(proposer.calls) == 2 and len(e.runner.calls) == 1
    resumed = AutonomousAFS(e.root, runner=e.runner, proposer=proposer, fingerprint_fn=fingerprint)
    result = resumed.run(live=True)
    assert result["status"] == "COMPLETE"
    assert len(proposer.calls) == len(e.runner.calls) == 3
    for ctx in proposer.calls:
        assert ctx["failure_objective"]["coverage_priority_scope"] == "new_session_attempts_only"
    assert result["budget"]["feedback_policy"] == "action-diagnostics-v1"
    assert "action-search-diagnostics-v1" in resumed.report().read_text()
