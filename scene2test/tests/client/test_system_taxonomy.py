"""System-interface candidates and blame separation; CPU fixtures only."""

import json
import runpy
from copy import deepcopy
from hashlib import sha256

import pytest

from failure_client.evaluation.research_records import (
    EXPANDED_FAMILIES,
    SYSTEM_FAMILIES,
    Attribution,
)
from failure_client.evaluation.system_taxonomy import (
    RULES,
    classify_system,
    interface_observations,
    state_contract_observations,
)
from failure_client.evaluation.taxonomy_profiles import metric_options
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics

from .test_discovery_measures import episode, load
from .test_expanded_taxonomy import action, progress
from .test_usage_taxonomy import dense_archive

GOAL = {"target_xy_m": [7.0, 0.0], "radius_m": 0.25, "dwell_s": 1.0}


def test_policy_output_state_mismatch_distinct_from_pose_staleness_or_body_fault():
    diagnostic = state_contract_observations(
        [
            {
                "observation_version": 4,
                "action": {"state_version": 5},
                "execution": "stale_rejected",
            },
            {
                "observation_version": 6,
                "action": {"state_version": 6},
                "execution": "stale_rejected",
            },
        ],
        "verified_hash",
    )
    assert diagnostic["status"] == "VIOLATION_OBSERVED"
    assert len(diagnostic["events"]) == 1
    assert diagnostic["events"][0]["requested_state_version"] == 5
    assert diagnostic["events"][0]["sha256"] == "verified_hash"
    assert "not proof" in diagnostic["claim"]


def result(**changes):
    return {
        "task_outcome": "FAIL",
        "execution_valid": True,
        "reason": "BUDGET_EXHAUSTED",
        "goal_progress": progress(distance_m=0.6, inside_goal_region=False, current_dwell_s=0),
        **changes,
    }


def block(target=None):
    return action("navigate_to", target_xy_m=target or [7.0, 0.0], tool_status="blocked_endpoint")


def arrival(x=6.88, y=-0.62):
    return action(
        "navigate_to", target_xy_m=[x, y], tool_status="target_reached", goal_distance_m=0.7
    )


def observe(actions, **kwargs):
    return interface_observations(actions, result(), GOAL, actions_available=True, **kwargs)


def test_goal_endpoint_rejection_requires_repetition_and_final_action():
    rows = [block(), arrival(), block()]
    before = deepcopy(rows)
    f, m = observe(rows)
    assert f["goal_endpoint_rejection"] == "DETECTED"
    assert f["subgoal_completion_loop"] == "NOT_DETECTED"
    assert m["goal_endpoint_rejection"]["whole_episode_goal_blocks"] == 2 and rows == before
    for bad in ([block()], [block(), block(), arrival()], [block([6.0, 0.0]), block()]):
        assert observe(bad)[0]["goal_endpoint_rejection"] == "NOT_DETECTED"


def test_known_stale_rejection_not_executed_or_silently_skipped_at_terminal():
    stale = action("navigate_to", target_xy_m=[6.0, 0.5], execution="stale_rejected")
    stale.censored = True
    assert observe([block(), stale, block()])[0]["goal_endpoint_rejection"] == "DETECTED"
    assert observe([block(), block(), stale])[0]["goal_endpoint_rejection"] == "UNKNOWN"


def test_consecutive_terminal_subgoal_success_loop_not_normal_waypoints():
    rows = [block(), arrival(), arrival(), arrival(6.93, -0.52)]
    f, m = observe(rows)
    assert f["subgoal_completion_loop"] == "DETECTED"
    assert m["subgoal_completion_loop"]["most_repeated_subgoal_count"] == 2
    for bad in (
        [arrival(), arrival()],
        [arrival(2), arrival(4), arrival(6)],
        [arrival(), arrival(), arrival(), action()],
    ):
        assert observe(bad)[0]["subgoal_completion_loop"] == "NOT_DETECTED"


@pytest.mark.parametrize(
    "case", ["unavailable", "censored", "target", "progress", "trailing_reject"]
)
def test_partial_evidence_unknown_not_new_failure(case):
    rows = [block(), block()]
    r = result()
    available = True
    if case == "unavailable":
        available = False
    elif case == "censored":
        rows[-1].censored = True
    elif case == "target":
        rows[-1].details.pop("target_xy_m")
    elif case == "progress":
        r["goal_progress"] = {}
    else:
        rows[-1].details["execution"] = "rejected"
    f, _ = interface_observations(rows, r, GOAL, actions_available=available)
    assert all(v == "UNKNOWN" for v in f.values())


@pytest.mark.parametrize(
    "changes",
    [
        {"task_outcome": "PASS"},
        {"reason": "POLICY_STOP"},
        {"execution_valid": False},
        {"task_outcome": "INCONCLUSIVE", "reason": "api_timeout"},
    ],
)
def test_not_every_budget_stop_or_pass_is_new_family(changes):
    f, _ = interface_observations(
        [block(), block()], result(**changes), GOAL, actions_available=True
    )
    assert all(v != "DETECTED" for v in f.values())


def test_turn_repetition_diagnostic_only():
    turn = action("move", vx_mps=0.0, vy_mps=0.0, yaw_rate_rps=0.4)
    f, m = observe([turn, turn])
    assert m["terminal_repeated_turns"]["status"] == "OBSERVED"
    assert all(v == "NOT_DETECTED" for v in f.values())


def test_inventory_explicit_and_old_defaults_unchanged():
    a = Attribution(
        primary_family="goal_endpoint_rejection",
        rule_version=RULES["goal_endpoint_rejection"],
        evidence_refs=["events.jsonl"],
    )
    r = episode(0, attribution=a)
    with pytest.raises(ValueError):
        calculate_discovery_metrics([r], family_rules=RULES)
    m = calculate_discovery_metrics([r], family_rules=RULES, family_inventory=SYSTEM_FAMILIES)
    assert m["targets"]["family_denominator"] == 12
    assert m["groups"][0]["discovered_family_count"] == 1
    assert (
        metric_options("clear-path-human-v5", "expanded-ten-v1")["family_inventory"]
        == EXPANDED_FAMILIES
    )
    assert calculate_discovery_metrics([episode(1)])["targets"]["family_denominator"] == 6


@pytest.mark.parametrize("outcome", ["PASS", "FAIL"])
def test_wrapper_preserves_source_outcomes_and_unconfirmed_layers(tmp_path, outcome):
    root = dense_archive(tmp_path / "source", outcome=outcome)
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    r = classify_system(load(root))
    assert r.task_outcome == outcome
    assert r.taxonomy["failure_layers"]["agent_fault"] == "UNCONFIRMED"
    assert r.taxonomy["failure_layers"]["vla_fault"] == "NOT_SEPARATELY_INSTRUMENTED"
    assert r.taxonomy["failure_layers"]["robot_body_fault"] == "UNCONFIRMED"
    if outcome == "PASS":
        assert r.attribution is None
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}


def test_existing_primary_and_legacy_ambiguity_preserved(tmp_path, monkeypatch):
    import failure_client.evaluation.system_taxonomy as module

    root = dense_archive(tmp_path / "source", collision=True)
    monkeypatch.setattr(
        module,
        "interface_observations",
        lambda *a, **kw: (
            {"goal_endpoint_rejection": "DETECTED", "subgoal_completion_loop": "NOT_DETECTED"},
            {},
        ),
    )
    assert classify_system(load(root)).attribution.primary_family == "collision"
    base = module.classify_expanded(load(root))
    base.attribution = None
    base.taxonomy.update(primary_family=None)
    base.taxonomy["warnings"].append("ambiguous_multiple_families")
    monkeypatch.setattr(module, "classify_expanded", lambda r: base)
    assert classify_system(load(root)).attribution is None


def test_missing_trace_exclusion_stays_excluded(tmp_path):
    root = dense_archive(tmp_path / "source")
    (root / "states.jsonl").unlink()
    original = load(root)
    r = classify_system(original)
    assert r.status == original.status != "VALID" and r.attribution is None
    assert all(r.taxonomy["families"][f]["status"] == "UNKNOWN" for f in SYSTEM_FAMILIES[-2:])


def test_reanalysis_separate_new_report_and_no_prospective_credit(tmp_path):
    tool = runpy.run_path("tools/reanalyze_system_failures.py")
    root = dense_archive(tmp_path / "source")
    report, m = tool["analyze"]([root], tmp_path / "output")
    assert "12종" in report.read_text()
    assert m["analysis_scope"]["prospective_joint_target_achieved"] is False
    assert m["analysis_scope"]["original_ten_family_metrics"]["targets"]["family_denominator"] == 10
    assert json.loads((report.parent / "metrics.json").read_text())["analysis_scope"][
        "verdicts_preserved"
    ]
    with pytest.raises(ValueError):
        tool["analyze"]([root], tmp_path / "output")


def test_report_snapshot_identity_and_manifest_tamper_rejected(tmp_path):
    tool = runpy.run_path("tools/reanalyze_system_failures.py")
    session = tmp_path / "session"
    (session / "attempts/attempt_00000").mkdir(parents=True)
    root = dense_archive(session / "attempts/attempt_00000/rollout")
    report = session / "reports/snapshot"
    report.mkdir(parents=True)
    attempts = [{"episode": load(root).model_dump()}]

    def write_snapshot():
        (report / "attempts.json").write_text(json.dumps(attempts))
        (report / "summary.json").write_text(json.dumps({"pending": None, "status": "READY"}))
        (report / "manifest.json").write_text(
            json.dumps(
                {
                    "artifacts": [
                        {"path": name, "sha256": sha256((report / name).read_bytes()).hexdigest()}
                        for name in ("attempts.json", "summary.json")
                    ]
                }
            )
        )

    write_snapshot()
    assert tool["snapshot_paths"](session) == [root.resolve()]
    attempts[0]["episode"]["evidence_id"] = "forged"
    write_snapshot()
    with pytest.raises(ValueError, match="changed since"):
        tool["snapshot_paths"](session)
    (report / "summary.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact changed"):
        tool["snapshot_paths"](session)
