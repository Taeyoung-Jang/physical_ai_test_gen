"""Bounded observational search memory; never verdicts, family rules or causal labels."""

import math
from collections import Counter

from llm_afs.behavior import digest

VERSION = "trajectory-feedback-v1"
BLOCKED = {"blocked_endpoint", "no_path", "no_tracking_clearance"}
MANIPULATION = {"push_object", "pick_object", "place_object"}
PROGRESS_MIN_M = 0.05  # Search summary heuristic only, never a detector or outcome threshold.


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def trajectory(entry, goal):
    record, behavior = entry["record"], entry["behavior"]
    action_status = behavior.get("components", {}).get("actions")
    available = action_status in {"AVAILABLE", "PARTIAL"}
    windows = [i for i in behavior.get("intervals", []) if i["kind"] == "action_window"]
    complete = (
        action_status == "AVAILABLE"
        and bool(windows)
        and all(not i.get("censored", True) for i in windows)
    )
    actions = [
        i["details"]
        for i in windows
        if available and not i.get("censored", True) and i["details"].get("execution") == "accepted"
    ]
    target = goal.get("target_xy_m")
    radius = goal.get("radius_m")
    blocked, goal_blocked, positive_progress, manipulations, arrivals = [], [], [], [], []
    for d in actions:
        nav = d.get("action") in {"navigate_to", "plan_path"}
        if nav and d.get("tool_status") in BLOCKED:
            blocked.append(d)
            xy = d.get("target_xy_m")
            if xy is not None and target is not None and math.dist(xy, target) <= 1e-6:
                goal_blocked.append(d)
        progress = d.get("motion_goal_distance_reduction_m")
        if (
            d.get("action") in {"navigate_to", "move"}
            and number(progress)
            and progress >= PROGRESS_MIN_M
        ):
            positive_progress.append(d)
        if d.get("action") in MANIPULATION:
            manipulations.append(d)
        distance = d.get("goal_distance_m")
        if d.get("tool_status") == "target_reached" and number(distance) and number(radius):
            if distance > radius:
                arrivals.append(d)
    # A locally rejected action is still an observed request, not physical engagement.
    manipulation_requests = [
        i["details"]
        for i in windows
        if available and not i.get("censored", True) and i["details"].get("action") in MANIPULATION
    ]
    taxonomy = record.get("taxonomy") or {}
    measured = taxonomy.get("measurements", {})
    final = measured.get("expanded_behavior", {}).get("goal_completion_failure")
    final = final if isinstance(final, dict) else {}
    distance = final.get("distance_m")
    entered = [
        d
        for d in actions
        if number(d.get("goal_distance_m")) and number(radius) and d["goal_distance_m"] <= radius
    ]
    failed = record.get("status") == "VALID" and record.get("task_outcome") == "FAIL"
    exhausted = record.get("termination_reason") == "BUDGET_EXHAUSTED"

    def observed(value):
        return True if value else False if complete else None

    patterns = {
        "blocked_goal_then_progress_budget_fail": observed(
            failed
            and exhausted
            and any(
                j > i
                for i, b in enumerate(actions)
                if b in goal_blocked
                for j, p in enumerate(actions)
                if p in positive_progress
            )
        ),
        "staging_arrival_outside_goal": observed(bool(arrivals)),
        "manipulation_tool_rejected": observed(
            any(
                d.get("tool_status") in {"rejected", "failed", "failure", "aborted"}
                for d in manipulations
            )
        ),
        "no_manipulation_request": (False if manipulation_requests else True if complete else None),
        "entered_goal_then_finished_outside": (
            bool(entered) and distance > radius
            if complete and number(distance) and number(radius)
            else None
        ),
    }
    endpoints = Counter(
        tuple(d["target_xy_m"]) for d in blocked if d.get("target_xy_m") is not None
    )
    return {
        "version": VERSION,
        "evidence_id": record.get("evidence_id"),
        "outcome": record.get("task_outcome"),
        "termination": record.get("termination_reason"),
        "action_results_complete": complete,
        "observed_blocked_requests": len(blocked) if available else None,
        "observed_goal_endpoint_blocks": len(goal_blocked) if available else None,
        "repeated_blocked_endpoints": [
            {"target_xy_m": list(xy), "count": count}
            for xy, count in sorted(endpoints.items())
            if count > 1
        ],
        "progress_action_versions": [d.get("observation_version") for d in positive_progress],
        "progress_summary_min_reduction_m": PROGRESS_MIN_M,
        "manipulation_results": [
            {
                k: d.get(k)
                for k in (
                    "observation_version",
                    "action",
                    "execution",
                    "tool_status",
                    "tool_reason",
                )
            }
            for d in manipulation_requests
        ],
        "goal_entry_action_versions": [d.get("observation_version") for d in entered],
        "goal_entry_dwell_s": [d.get("goal_current_dwell_s") for d in entered],
        "goal_entry_sampling": "Observed action-result poses only; not all full-rate crossings",
        "final_full_rate_goal_progress": final or None,
        "last_actions": [
            {
                k: d.get(k)
                for k in (
                    "observation_version",
                    "action",
                    "tool_status",
                    "goal_distance_m",
                    "goal_current_dwell_s",
                    "motion_net_translation_m",
                )
            }
            for d in actions[-3:]
        ],
        "patterns": patterns,
        "primary_family": (record.get("attribution") or {}).get("primary_family"),
        "claim": "Descriptive observations only; partial absence is UNKNOWN, not a family/cause",
    }


def prediction_check(attempt, entry):
    record = entry["record"]
    predicted = attempt["candidate"].get("evidence", {}).get("target_family")
    tax = record.get("taxonomy") or {}
    status = tax.get("families", {}).get(predicted, {}).get("status", "UNKNOWN")
    if record.get("status") != "VALID":
        status = "UNRESOLVED_EXCLUDED"
    measured = tax.get("measurements", {})
    return {
        "attempt_id": attempt.get("id"),
        "evidence_id": record.get("evidence_id"),
        "predicted_family": predicted,
        "observed_goal_outcome": record.get("task_outcome"),
        "predicted_detector_status": status,
        "observed_primary_family": (record.get("attribution") or {}).get("primary_family"),
        "gate_observations": {
            "terminal_progress": measured.get("terminal_progress"),
            "recent_blocked_count": len(measured["blocked_tools"])
            if "blocked_tools" in measured
            else None,
            "qualifying_contact_count": measured.get("non_support_contacts", {}).get("count"),
            "expanded_behavior": measured.get("expanded_behavior"),
        },
        "assessment": "Predicted observation absent, not a causal falsification"
        if status == "NOT_DETECTED"
        else "Use fixed detector status; never overwrite goal outcome",
    }


def feedback(memory, attempts, shown):
    """Accumulate beyond displayed history, separated by condition, task and origin."""
    current = {a.get("episode", {}).get("evidence_id") for a in attempts}
    contracts = {ref: case["task_contract"] for case in memory["cases"] for ref in case["episodes"]}
    summaries, groups = {}, {}
    for ref, entry in sorted(memory["episodes"].items()):
        r = entry["record"]
        if r.get("status") != "VALID" or ref not in contracts:
            continue
        task = contracts[ref]
        summary = trajectory(entry, task["goal"])
        summaries[ref] = summary
        scope = "current" if ref in current else "historical"
        key = digest([scope, r.get("condition_id"), task, r.get("policy_origin")])
        group = groups.setdefault(
            key,
            {
                "scope": scope,
                "condition_id": r.get("condition_id"),
                "task_contract_sha256": digest(task),
                "episode_budget": task.get("episode_budget"),
                "policy_origin": r.get("policy_origin"),
                "valid_episodes": 0,
                "failures": 0,
                "pattern_counts": Counter(),
                "representatives": {},
            },
        )
        group["valid_episodes"] += 1
        if r.get("task_outcome") != "FAIL":
            continue
        group["failures"] += 1
        for name, value in summary["patterns"].items():
            if value is not True:
                continue
            group["pattern_counts"][name] += 1
            refs = group["representatives"].setdefault(name, [])
            if len(refs) < 2:
                refs.append({"evidence_id": ref, "presented_detail": ref in shown})
    rows = sorted(
        groups.values(),
        key=lambda g: (g["scope"] != "current", g["condition_id"] or "", g["task_contract_sha256"]),
    )
    checks = [
        {
            **prediction_check(a, memory["episodes"][ref]),
            "condition_id": memory["episodes"][ref]["record"].get("condition_id"),
            "policy_origin": memory["episodes"][ref]["record"].get("policy_origin"),
            "task_contract_sha256": digest(contracts[ref]),
        }
        for a in attempts
        if (ref := a.get("episode", {}).get("evidence_id")) in summaries
        and a["candidate"].get("evidence", {}).get("target_family") is not None
    ]
    counts = Counter(
        (
            c["condition_id"],
            c["task_contract_sha256"],
            c["policy_origin"],
            c["predicted_family"],
            c["predicted_detector_status"],
        )
        for c in checks
    )
    return {
        "version": VERSION,
        "presented_episode_summaries": [summaries[ref] for ref in shown if ref in summaries],
        "condition_groups": rows[:8],
        "omitted_condition_groups": max(0, len(rows) - 8),
        "recent_prediction_checks": checks[-4:],
        "prediction_status_counts": [
            {
                "condition_id": condition,
                "task_contract_sha256": task,
                "policy_origin": origin,
                "predicted_family": family,
                "detector_status": status,
                "count": count,
            }
            for (condition, task, origin, family, status), count in sorted(
                counts.items(), key=lambda x: str(x[0])
            )
        ],
        "scope": "Supplied same-run memory only; no external or cross-seed archive retrieval",
        "claim": "Pattern counts are overlapping FAIL episode counts, not distinct family coverage",
        "selection_effect": (
            "LLM feedback only; host ranking, quotas and candidate guards unchanged"
        ),
        "guidance": (
            "A different predicted family name is not a different observed behavior. "
            "Compare repeated patterns and detector gates. In change_rationale explain which "
            "environment change may exercise a different behavior and why; in measurement_plan "
            "state what would distinguish it. Preserve useful small probes; no hard pattern ban. "
            "Do not prescribe robot commands, weaken rules, increase budgets or relabel FAIL. "
            "Representatives without presented_detail are aggregate provenance, not citable "
            "anchor/analysis IDs. Use only allowed presented references in proposals."
        ),
    }
