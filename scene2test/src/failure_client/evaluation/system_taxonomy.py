"""Opt-in observed planning/task-sequencing failures, never component blame.

Old six/ten-family profiles and raw goal outcomes remain unchanged. New rules are
retrospective candidates, not proof that an Agent, VLA, planner or body caused FAIL.
"""

import math
from copy import deepcopy

from .behavior_measures import analyze_behavior, verify_episode_files
from .expanded_taxonomy import RULES as TEN_RULES
from .expanded_taxonomy import classify_expanded
from .goal_run_reader import _rows, read_json
from .research_records import SYSTEM_FAMILIES, Attribution, EpisodeRecord

PROFILE = "system-twelve-v1"
NEW_FAMILIES = SYSTEM_FAMILIES[-2:]
RULES = {**TEN_RULES, **{f: PROFILE + "/" + f for f in NEW_FAMILIES}}
THRESHOLDS = {
    "goal_target_tolerance_m": 1e-6,
    "goal_endpoint_rejections": 2,
    "terminal_subgoal_arrivals": 3,
    "same_subgoal_arrivals": 2,
    "same_subgoal_tolerance_m": 0.02,
    "diagnostic_terminal_turns": 2,
    "diagnostic_turn_execution_s": 1.0,
}


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _point(value):
    return isinstance(value, list) and len(value) == 2 and all(_number(v) for v in value)


def state_contract_observations(rows, source_hash):
    mismatches = []
    for line, row in enumerate(rows, 1):
        action = row.get("action")
        if not isinstance(action, dict):
            continue
        expected, requested = row.get("observation_version"), action.get("state_version")
        if (
            row.get("execution") == "stale_rejected"
            and type(expected) is int
            and type(requested) is int
            and expected != requested
        ):
            mismatches.append(
                {
                    "observation_version": expected,
                    "requested_state_version": requested,
                    "execution": "stale_rejected",
                    "artifact": "decisions.jsonl",
                    "line": line,
                    "sha256": source_hash,
                }
            )
    return {
        "status": "VIOLATION_OBSERVED" if mismatches else "NOT_OBSERVED",
        "events": mismatches,
        "claim": "Policy output violated state-version contract; not proof it caused task FAIL",
    }


def interface_observations(actions, result, goal, *, actions_available):
    """Pure sequence rules over verified action windows; no NLP or LLM labels."""
    statuses = dict.fromkeys(NEW_FAMILIES, "UNKNOWN")
    measures = {"eligibility": "UNKNOWN", "terminal_repeated_turns": {"status": "UNKNOWN"}}
    rows = [a.model_dump(mode="json") if hasattr(a, "model_dump") else a for a in actions]
    if (
        not actions_available
        or not rows
        or any(
            a.get("censored", True) and a.get("details", {}).get("execution") != "stale_rejected"
            for a in rows
        )
    ):
        measures["unknown_reason"] = "missing_or_partial_executed_action_results"
        return statuses, measures
    if any(
        a.get("details", {}).get("execution") not in {"accepted", "rejected", "stale_rejected"}
        for a in rows
    ):
        return statuses, measures
    accepted = [a for a in rows if a["details"]["execution"] == "accepted"]
    if not accepted:
        return statuses, measures
    # Do not silently skip a trailing locally rejected action and call its predecessor terminal.
    if rows[-1]["details"]["execution"] != "accepted":
        measures["unknown_reason"] = "terminal_action_not_executed"
        return statuses, measures
    progress = result.get("goal_progress") or {}
    radius, dwell = goal.get("radius_m"), goal.get("dwell_s")
    distance, current = progress.get("distance_m"), progress.get("current_dwell_s")
    if not (
        _point(goal.get("target_xy_m"))
        and all(_number(v) and v >= 0 for v in (radius, dwell, distance, current))
        and progress.get("radius_m") == radius
        and progress.get("required_dwell_s") == dwell
        and type(progress.get("inside_goal_region")) is bool
        and type(progress.get("goal_reached")) is bool
        and progress["inside_goal_region"] == (distance <= radius)
        and progress["goal_reached"] == (distance <= radius and current >= dwell - 1e-9)
    ):
        return statuses, measures
    eligible = (
        result.get("task_outcome") == "FAIL"
        and result.get("execution_valid") is True
        and result.get("reason") == "BUDGET_EXHAUSTED"
        and distance > radius
    )
    measures["eligibility"] = "FAIL_BUDGET_FINAL_OUTSIDE" if eligible else "NOT_ELIGIBLE"
    if not eligible:
        return dict.fromkeys(NEW_FAMILIES, "NOT_DETECTED"), measures
    # Missing navigation targets/results are not evidence that a sequence did not occur.
    if any(
        a["details"].get("action") in {"plan_path", "navigate_to"}
        and (
            not _point(a["details"].get("target_xy_m"))
            or not isinstance(a["details"].get("tool_status"), str)
        )
        for a in accepted
    ):
        return statuses, measures
    statuses = dict.fromkeys(NEW_FAMILIES, "NOT_DETECTED")

    def goal_rejection(row):
        d = row["details"]
        return (
            d.get("action") in {"navigate_to", "plan_path"}
            and d.get("tool_status") == "blocked_endpoint"
            and math.dist(d["target_xy_m"], goal["target_xy_m"])
            <= THRESHOLDS["goal_target_tolerance_m"]
        )

    blocked = [a for a in accepted if goal_rejection(a)]
    if len(blocked) >= THRESHOLDS["goal_endpoint_rejections"] and goal_rejection(rows[-1]):
        statuses["goal_endpoint_rejection"] = "DETECTED"
    measures["goal_endpoint_rejection"] = {
        "whole_episode_goal_blocks": len(blocked),
        "last_action_is_goal_block": goal_rejection(rows[-1]),
        "matching_actions": blocked,
        "scope": "Whole episode plus final action, not terminal-time collision/interference",
        "excludes": (
            "Not a proof of unreachability, planner bug, perception error or body incapacity"
        ),
    }

    suffix = []
    for a in reversed(rows):
        d = a["details"]
        if not (
            d.get("execution") == "accepted"
            and d.get("action") == "navigate_to"
            and d.get("tool_status") == "target_reached"
            and _point(d.get("target_xy_m"))
            and _number(d.get("goal_distance_m"))
            and d["goal_distance_m"] > radius
            and math.dist(d["target_xy_m"], goal["target_xy_m"]) > radius
        ):
            break
        suffix.append(a)
    suffix.reverse()
    repeated = max(
        (
            sum(
                math.dist(a["details"]["target_xy_m"], b["details"]["target_xy_m"])
                <= THRESHOLDS["same_subgoal_tolerance_m"]
                for b in suffix
            )
            for a in suffix
        ),
        default=0,
    )
    if (
        len(suffix) >= THRESHOLDS["terminal_subgoal_arrivals"]
        and repeated >= THRESHOLDS["same_subgoal_arrivals"]
    ):
        statuses["subgoal_completion_loop"] = "DETECTED"
    measures["subgoal_completion_loop"] = {
        "consecutive_terminal_subgoal_arrivals": len(suffix),
        "most_repeated_subgoal_count": repeated,
        "matching_actions": suffix,
        "excludes": "No claim of agent misunderstanding; distinct normal waypoints alone excluded",
    }
    turns = []
    for a in reversed(rows):
        d = a["details"]
        if not (
            d.get("execution") == "accepted"
            and d.get("action") == "move"
            and d.get("vx_mps") == 0
            and d.get("vy_mps") == 0
            and _number(d.get("yaw_rate_rps"))
            and abs(d["yaw_rate_rps"]) > 0
            and _number(d.get("motion_elapsed_s"))
            and d["motion_elapsed_s"] >= THRESHOLDS["diagnostic_turn_execution_s"]
        ):
            break
        turns.append(a)
    measures["terminal_repeated_turns"] = {
        "status": "OBSERVED"
        if len(turns) >= THRESHOLDS["diagnostic_terminal_turns"]
        else "NOT_OBSERVED",
        "count": len(turns),
        "actions": list(reversed(turns)),
        "claim": "Intentional turn commands, diagnostic only; not physical locomotion stall",
    }
    return statuses, measures


def classify_system(record):
    base = classify_expanded(record)
    report = deepcopy(base.taxonomy)
    report.update(
        schema_version=PROFILE,
        family_inventory=list(SYSTEM_FAMILIES),
        system_thresholds=dict(THRESHOLDS),
        legacy_profile="expanded-goal-behavior-v1",
        primary_selection="Preserve ten-family primary/ambiguity; else unique new observation",
    )
    report["families"].update(
        {f: {"status": "UNKNOWN", "rule_version": RULES[f]} for f in NEW_FAMILIES}
    )
    report["failure_layers"] = {
        "version": "observed-interface-layers-v1",
        "root_cause_status": "UNCONFIRMED",
        "agent_fault": "UNCONFIRMED",
        "planner_fault": "UNCONFIRMED",
        "vla_fault": "NOT_SEPARATELY_INSTRUMENTED",
        "controller_fault": "UNCONFIRMED",
        "robot_body_fault": "UNCONFIRMED",
        "claim": "Localize observed interfaces, not the component that caused the failure",
    }
    if record.status == "VALID":
        root = verify_episode_files(record)
        protocol = read_json(root / "protocol.json")
        behavior = analyze_behavior(record)
        findings, measurements = interface_observations(
            [i for i in behavior.intervals if i.kind == "action_window"],
            read_json(root / "result.json"),
            protocol["task_contract"]["goal"],
            actions_available=behavior.components.get("actions") == "AVAILABLE",
        )
        report["measurements"]["system_interfaces"] = measurements
        report["failure_layers"]["recorded_stack"] = {
            k: protocol.get(k)
            for k in (
                "model",
                "policy_origin",
                "prompt_version",
                "robot_internal_planner",
                "navigation_follower",
                "controller_condition",
                "observation",
            )
        }
        report["failure_layers"]["observed_interfaces"] = [
            interface
            for f, interface in zip(
                NEW_FAMILIES,
                ("goal_target_to_navigation_planner", "policy_subgoals_to_task_completion"),
            )
            if findings[f] == "DETECTED" and record.task_outcome == "FAIL"
        ]
        state_contract = state_contract_observations(
            _rows(root / "decisions.jsonl"), record.artifact_hashes["decisions.jsonl"]
        )
        report["failure_layers"]["policy_state_contract"] = state_contract
        if state_contract["events"]:
            report["failure_layers"]["observed_interfaces"].append("policy_state_to_executor_guard")
        for f, status in findings.items():
            report["families"][f]["status"] = status if record.task_outcome == "FAIL" else "N/A"
            if record.task_outcome == "PASS":
                report["families"][f]["diagnostic_status"] = status
        if (
            record.task_outcome == "FAIL"
            and not report.get("primary_family")
            and "ambiguous_multiple_families" not in report.get("warnings", [])
        ):
            detected = [f for f in NEW_FAMILIES if findings[f] == "DETECTED"]
            if len(detected) == 1:
                report["primary_family"] = detected[0]
            elif len(detected) > 1:
                report["warnings"].append("ambiguous_system_interface_families")
    report["diagnostic_families"] = [
        f for f, v in report["families"].items() if v["status"] == "DETECTED"
    ]
    report["limits"].extend(
        [
            "Retrospective twelve-family candidate contract, not prospective achievement",
            "Observed interface failures do not assign blame to Agent/VLA/controller/body",
            "Rotation repetition stays diagnostic; no invented extra discovered family",
        ]
    )
    family = report.get("primary_family")
    attribution = (
        Attribution(
            primary_family=family,
            rule_version=RULES[family],
            evidence_refs=sorted({e["artifact"] for e in report["evidence"]}),
        )
        if family
        else None
    )
    return EpisodeRecord.model_validate(
        {
            **base.model_dump(),
            "taxonomy": report,
            "attribution": attribution.model_dump() if attribution else None,
        }
    )
