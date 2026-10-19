"""Whole-episode search feedback, never a verdict, family detector or causal oracle."""

from collections import Counter

BLOCKED = {"blocked_endpoint", "no_path", "no_tracking_clearance"}


def action_diagnostics(entry, goal):
    behavior, record = entry["behavior"], entry["record"]
    available = behavior.get("components", {}).get("actions") == "AVAILABLE"
    result = {
        "version": "action-search-diagnostics-v1",
        "status": "AVAILABLE" if available else "UNAVAILABLE",
        "claim": "Whole episode tool observations; not measured families or physical causes",
        "final_goal_distance_m": (record.get("measures") or {}).get("last_sample_goal_distance_m"),
    }
    if not available:
        return result
    actions = [i for i in behavior.get("intervals", []) if i["kind"] == "action_window"]
    complete = all(not i.get("censored", True) for i in actions)
    counts = Counter(i["details"].get("action") for i in actions)
    blocked, reached_outside = [], []
    endpoints = Counter()
    for i in actions:
        d = i["details"]
        if i.get("censored", True) or d.get("execution") != "accepted":
            continue
        ref = {
            "observation_version": d.get("observation_version"),
            "action": d.get("action"),
            "target_xy_m": d.get("target_xy_m"),
            "tool_status": d.get("tool_status"),
            "evidence": i.get("evidence", []),
        }
        if d.get("action") in {"navigate_to", "plan_path"} and d.get("tool_status") in BLOCKED:
            blocked.append(ref)
            if d.get("target_xy_m") is not None:
                endpoints[tuple(d["target_xy_m"])] += 1
        distance = d.get("goal_distance_m")
        if (
            d.get("tool_status") == "target_reached"
            and distance is not None
            and goal.get("radius_m") is not None
            and distance > goal["radius_m"]
        ):
            reached_outside.append({**ref, "goal_distance_m": distance})
    pushes = [i for i in actions if i["details"].get("action") == "push_object"]
    result.update(
        action_count=len(actions),
        action_counts=dict(counts),
        complete_action_results=complete,
        blocked_navigation_count=len(blocked),
        first_blocked_navigation=blocked[0] if blocked else None,
        repeated_blocked_endpoints=[
            {"target_xy_m": list(p), "count": n} for p, n in endpoints.items() if n > 1
        ],
        staging_arrivals_outside_goal=reached_outside,
        manipulation_engagement=(
            "TOOL_REQUEST_OBSERVED_NOT_PHYSICAL_SUCCESS"
            if pushes
            else "NO_TOOL_REQUEST_OBSERVED"
            if complete
            else "UNKNOWN_PARTIAL_RESULTS"
        ),
        response_guidance=(
            "Compare actual action patterns, not only changed axes. Repeated blocked endpoints "
            "do not establish collision, unreachability or a friction cause. No push request "
            "does not test physical pushing capacity. Inference waits are not motion stalls. "
            "Consider other admissible anchors/layouts when the same pattern repeats; "
            "never prescribe robot actions or modify a running scene."
        ),
    )
    return result
