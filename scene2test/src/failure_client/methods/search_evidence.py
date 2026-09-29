"""Bounded AFS evidence and heuristic behavior similarity; never a failure oracle."""

from __future__ import annotations

import math
from collections import Counter

from llm_afs.behavior import digest

VERSION = "behavior-search-evidence-v2"
SIGNATURE_VERSION = "behavior-pattern-v1"
DETAIL_LIMIT = 12


def _eligible(behavior):
    return [i for i in behavior.get("intervals", []) if not i["details"].get("support_contact")]


def _action_summary(interval):
    keys = (
        "observation_version",
        "action",
        "execution",
        "target_xy_m",
        "object_id",
        "duration_s",
        "vx_mps",
        "vy_mps",
        "yaw_rate_rps",
        "tool_status",
        "tool_reason",
        "tool_success",
        "tool_terminal_reason",
        "inference_wall_s",
    )
    return {
        "start_s": interval["start_s"],
        "end_s": interval["end_s"],
        "timing": interval["timing"],
        "censored": interval["censored"],
        **{k: interval["details"][k] for k in keys if k in interval["details"]},
        "evidence": interval["evidence"],
    }


def compact_evidence(entry, *, detail_limit=DETAIL_LIMIT):
    """Keep EVERY bounded episode action; budget only redundant detailed intervals.

    The importer caps episodes at 20 decisions. No invented execution timestamps,
    recovery success labels, or causal interpretation of a tool error.
    """
    if detail_limit < 1:
        raise ValueError("positive detail limit required")
    behavior = entry["behavior"]
    intervals = _eligible(behavior)
    actions = [i for i in intervals if i["kind"] == "action_window"]
    selected, reasons = [], {}

    def add(index, reason):
        if index in reasons:
            return
        if len(selected) < detail_limit:
            selected.append(index)
            reasons[index] = reason

    if intervals:
        add(len(intervals) - 1, "terminal_context")
        add(0, "initial_context")
    # Reserve representation across different event kinds, not just the first kind.
    for kind in ("fall", "recovery", "skill_event", "contact"):
        indices = [n for n, i in enumerate(intervals) if i["kind"] == kind]
        if indices:
            add(indices[-1], "latest_" + kind)
    exceptional = []
    for n, i in enumerate(intervals):
        d = i["details"]
        if i["kind"] == "action_window" and (
            d.get("execution") != "accepted"
            or d.get("tool_success") is False
            or d.get("tool_reason")
            or d.get("tool_status")
            not in (None, "executed", "path_found", "target_reached", "execution_slice_ended")
        ):
            exceptional.append(n)
    for n in reversed(exceptional):
        add(n, "tool_exception")
        following = next(
            (j for j in range(n + 1, len(intervals)) if intervals[j]["kind"] == "action_window"),
            None,
        )
        if following is not None:
            add(following, "action_after_exception")
    phases = [
        n
        for n, i in enumerate(intervals)
        if i["kind"] == "phase"
        and i.get("phase") not in ("settle", "inference_wait")
        and i["details"].get("goal_progress_m") is not None
    ]
    if phases:
        add(
            min(phases, key=lambda n: intervals[n]["details"]["goal_progress_m"]),
            "least_progress_phase",
        )
        add(
            max(phases, key=lambda n: intervals[n]["details"]["goal_progress_m"]),
            "most_progress_phase",
        )
    # Spread spare slots over the whole episode. Ties are deterministic.
    while len(selected) < min(detail_limit, len(intervals)):
        n = max(
            (n for n in range(len(intervals)) if n not in reasons),
            key=lambda n: min(abs(n - old) for old in selected),
        )
        add(n, "temporal_representative")
    selected.sort()
    return {
        "operational_taxonomy": {
            key: entry["record"].get("taxonomy", {}).get(key)
            for key in ("schema_version", "primary_family", "causal_status", "families", "warnings")
        },
        "action_timeline": [_action_summary(i) for i in actions],
        "action_timeline_status": behavior.get("components", {}).get("actions", "UNAVAILABLE"),
        "intervals": [intervals[n] for n in selected],
        "interval_count": len(intervals),
        "display_limit": detail_limit,
        "evidence_selection": {
            "version": VERSION,
            "actions_retained": len(actions),
            "selected_indices": selected,
            "reasons": [reasons[n] for n in selected],
            "omitted_detail_count": len(intervals) - len(selected),
            "counts_all_eligible": dict(Counter(i["kind"] for i in intervals)),
            "counts_selected": dict(Counter(intervals[n]["kind"] for n in selected)),
            "claim": "All action summaries retained; detailed events are representatives only",
        },
    }


def _bin(value, width):
    if type(value) not in (int, float) or not math.isfinite(value):
        return None
    return math.floor(value / width)


def behavior_signature(entry):
    """Stable coarse pattern, ignoring support contacts/count noise. Unknown != zero."""
    record, behavior = entry["record"], entry["behavior"]
    components = behavior.get("components", {})
    if record.get("status") != "VALID" or any(
        components.get(k) != "AVAILABLE" for k in ("states", "actions")
    ):
        return {"version": SIGNATURE_VERSION, "id": None, "status": "UNAVAILABLE"}
    actions, events = [], set()
    for i in _eligible(behavior):
        d = i["details"]
        if i["kind"] == "action_window":
            state = [
                d.get("action"),
                d.get("execution"),
                d.get("tool_status"),
                d.get("tool_reason"),
            ]
            if not actions or actions[-1] != state:
                actions.append(state)
        elif i["kind"] != "phase":
            events.add((i["kind"], d.get("world_geom_name"), d.get("robot_body")))
    measures = record.get("measures") or {}
    motion = behavior.get("object_motion", {})
    payload = {
        "version": SIGNATURE_VERSION,
        "termination": record.get("termination_reason"),
        "actions": actions,
        "events_status": components.get("events", "UNAVAILABLE"),
        "events": sorted(events, key=str),
        "goal_distance_bin_0_5m": _bin(measures.get("last_sample_goal_distance_m"), 0.5),
        "goal_progress_bin_0_5m": _bin(measures.get("sampled_progress_m"), 0.5),
        "box_motion_status": motion.get("status", "UNAVAILABLE"),
        "box_displacement_bin_0_1m": _bin(motion.get("net_xy_displacement_m"), 0.1),
    }
    return {
        "version": SIGNATURE_VERSION,
        "id": digest(payload),
        "status": "AVAILABLE",
        "features": payload,
    }
