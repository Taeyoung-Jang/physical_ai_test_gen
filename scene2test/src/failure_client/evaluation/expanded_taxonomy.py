"""Versioned ten-family retrospective diagnostics, not causal robot assessments.

Legacy profiles and goal verdicts stay unchanged. One primary family per episode;
additional observed events remain diagnostics, not extra discoveries.
"""

import math
from copy import deepcopy

from .behavior_measures import analyze_behavior, verify_episode_files
from .failure_taxonomy import HUMAN_PROFILE, _rotation, measure_taxonomy, rules_for_profile
from .goal_run_reader import _rows, read_json
from .research_records import EXPANDED_FAMILIES, Attribution, EpisodeRecord

PROFILE = "expanded-goal-behavior-v1"
NEW_FAMILIES = EXPANDED_FAMILIES[6:]
RULES = {**rules_for_profile(HUMAN_PROFILE), **{f: PROFILE + "/" + f for f in NEW_FAMILIES}}
THRESHOLDS = {
    "fall_height_m": 0.45,
    "fall_tilt_deg": 60.0,
    "fall_sustained_s": 0.5,
    "max_state_gap_s": 0.25,
    "stall_recent_s": 10.0,
    "stall_execution_s": 2.0,
    "stall_translation_m": 0.05,
    "stall_excursion_m": 0.1,
}
PRIORITY = ("fall", "goal_completion_failure", "locomotion_stall", "manipulation_failure")


def new_observations(states, actions, result, goal, *, actions_available=True):
    """Pure deterministic rules; all caller inputs must come from verified archives."""
    measurements = {}
    findings = {f: "UNKNOWN" for f in NEW_FAMILIES}
    complete = len(states) >= 2 and all(
        0 < b["time_s"] - a["time_s"] <= THRESHOLDS["max_state_gap_s"] + 1e-8
        for a, b in zip(states, states[1:])
    )
    if complete:
        start, longest = None, 0.0
        for s in states:
            tilt = math.degrees(math.acos(max(-1.0, min(1.0, _rotation(s["qpos"][3:7])[2, 2]))))
            fallen = (
                s["qpos"][2] < THRESHOLDS["fall_height_m"] or tilt >= THRESHOLDS["fall_tilt_deg"]
            )
            if fallen:
                start = s["time_s"] if start is None else start
                longest = max(longest, s["time_s"] - start)
            else:
                start = None
        findings["fall"] = "DETECTED" if longest >= 0.5 else "NOT_DETECTED"
        measurements["fall"] = {"longest_recorded_interval_s": longest}

    # Full-rate task evaluation state, not sampled max dwell and not every budget FAIL.
    progress = result.get("goal_progress")
    if isinstance(progress, dict) and all(
        k in progress
        for k in (
            "distance_m",
            "radius_m",
            "inside_goal_region",
            "required_dwell_s",
            "current_dwell_s",
            "goal_reached",
        )
    ):
        values = [
            progress[k] for k in ("distance_m", "radius_m", "required_dwell_s", "current_dwell_s")
        ]
        good = (
            all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in values)
            and progress["radius_m"] == goal["radius_m"]
            and progress["required_dwell_s"] == goal["dwell_s"]
            and type(progress["inside_goal_region"]) is bool
            and type(progress["goal_reached"]) is bool
            and progress["inside_goal_region"] == (progress["distance_m"] <= goal["radius_m"])
            and progress["goal_reached"]
            == (
                progress["inside_goal_region"]
                and progress["current_dwell_s"] >= goal["dwell_s"] - 1e-9
            )
        )
        if good:
            detected = (
                progress["inside_goal_region"]
                and not progress["goal_reached"]
                and 0 < progress["required_dwell_s"]
                and progress["current_dwell_s"] + 1e-8 < progress["required_dwell_s"]
            )
            findings["goal_completion_failure"] = "DETECTED" if detected else "NOT_DETECTED"
            measurements["goal_completion_failure"] = deepcopy(progress)

    if actions_available:
        stalls, missing = [], False
        end = states[-1]["time_s"] if states else None
        manipulation = {}
        for i in actions:
            d = i.details
            if d.get("execution") != "accepted":
                continue
            if d.get("action") in {"push_object", "pick_object", "place_object"}:
                # Last result per object: a later successful attempt supersedes a rejection.
                manipulation[d.get("object_id", "unknown_object")] = {
                    "observation_version": d.get("observation_version"),
                    "status": d.get("tool_status"),
                    "reason": d.get("tool_reason"),
                }
            if (
                d.get("action") not in {"navigate_to", "move"}
                or i.end_s is None
                or end is None
                or i.end_s < end - THRESHOLDS["stall_recent_s"]
            ):
                continue
            if d.get("tool_status") in {"target_reached", "goal_reached"}:
                continue
            if d.get("action") == "move" and all(
                d.get(k) == 0
                for k in (
                    "vx_mps",
                    "vy_mps",
                )
            ):
                continue
            elapsed, translation = d.get("motion_elapsed_s"), d.get("motion_net_translation_m")
            if elapsed is None or translation is None:
                missing = True
            elif (
                elapsed >= THRESHOLDS["stall_execution_s"]
                and translation <= THRESHOLDS["stall_translation_m"]
            ):
                start = d.get("execution_start_s")
                window = [
                    s for s in states if start is not None and start <= s["time_s"] <= i.end_s
                ]
                if (
                    not complete
                    or len(window) < 2
                    or start is None
                    or window[0]["time_s"] - start > 0.25
                    or i.end_s - window[-1]["time_s"] > 0.25
                ):
                    missing = True
                elif (
                    max(math.dist(s["qpos"][:2], window[0]["qpos"][:2]) for s in window)
                    <= THRESHOLDS["stall_excursion_m"]
                ):
                    stalls.append(i.model_dump(mode="json"))
        findings["locomotion_stall"] = (
            "DETECTED" if stalls else "UNKNOWN" if missing else "NOT_DETECTED"
        )
        failed = [
            r
            for r in manipulation.values()
            if r["status"]
            in {
                "rejected",
                "failed",
                "failure",
                "aborted",
            }
        ]
        unknown = any(
            r["status"]
            not in {
                "rejected",
                "failed",
                "failure",
                "aborted",
                "success",
                "succeeded",
                "completed",
            }
            for r in manipulation.values()
        )
        findings["manipulation_failure"] = (
            "DETECTED" if failed else "UNKNOWN" if unknown else "NOT_DETECTED"
        )
        measurements["locomotion_stall"] = {"execution_windows": stalls}
        measurements["manipulation_failure"] = {
            "last_result_per_object": manipulation,
            "interpretation": (
                "Includes execution rejection; not proof of physical pushing incapacity"
            ),
        }
    return findings, measurements


def classify_expanded(record):
    legacy = measure_taxonomy(record, profile=HUMAN_PROFILE)
    report = deepcopy(legacy)
    report.update(
        schema_version=PROFILE,
        legacy_profile=HUMAN_PROFILE,
        family_inventory=list(EXPANDED_FAMILIES),
        primary_family=None,
        primary_selection="legacy unique first, then " + ", ".join(PRIORITY),
        expanded_thresholds=dict(THRESHOLDS),
    )
    report["families"].update(
        {f: {"status": "UNKNOWN", "rule_version": RULES[f]} for f in NEW_FAMILIES}
    )
    if record.status == "VALID":
        root = verify_episode_files(record)
        behavior = analyze_behavior(record)
        states = list(_rows(root / "states.jsonl"))
        findings, measurements = new_observations(
            states,
            [i for i in behavior.intervals if i.kind == "action_window"],
            read_json(root / "result.json"),
            read_json(root / "protocol.json")["task_contract"]["goal"],
            actions_available=behavior.components.get("actions") == "AVAILABLE",
        )
        report["measurements"]["expanded_behavior"] = measurements
        for f, status in findings.items():
            report["families"][f]["status"] = status if record.task_outcome == "FAIL" else "N/A"
            if record.task_outcome == "PASS":
                report["families"][f]["diagnostic_status"] = status
        report["evidence"].extend(
            {"artifact": n, "sha256": record.artifact_hashes[n]}
            for n in ("states.jsonl", "decisions.jsonl", "result.json", "protocol.json")
        )
        if record.task_outcome == "FAIL":
            if legacy["primary_family"]:
                report["primary_family"] = legacy["primary_family"]
            elif "ambiguous_multiple_families" not in legacy["warnings"]:
                report["primary_family"] = next(
                    (f for f in PRIORITY if findings[f] == "DETECTED"), None
                )
    report["diagnostic_families"] = [
        f for f, r in report["families"].items() if r["status"] == "DETECTED"
    ]
    report["limits"].extend(
        [
            "One primary per episode; secondary detections are not extra discoveries",
            "Priority is a declared counting convention, NOT confirmed cause",
            "Expanded retrospective analysis, not a prospective ten-family validation",
        ]
    )
    family = report["primary_family"]
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
            **record.model_dump(),
            "taxonomy": report,
            "attribution": attribution.model_dump() if attribution else None,
        }
    )
