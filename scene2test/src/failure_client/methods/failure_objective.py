"""Measured coverage and bounded failure-seeking priorities; not a failure oracle."""

from collections import Counter

from failure_client.evaluation.failure_taxonomy import profile_for_scene, rules_for_profile
from failure_client.evaluation.research_records import EpisodeRecord
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics


def prediction_review(attempt):
    question = attempt["candidate"].get("evidence", {})
    row = attempt.get("episode") or {}
    outcome = row.get("task_outcome") if row.get("status") == "VALID" else None
    return {
        "attempt_id": attempt["id"],
        "axis": attempt["candidate"].get("axis"),
        "intent": question.get("intent"),
        "predicted_family": question.get("target_family"),
        "failure_prediction": question.get("failure_prediction", "")[:600],
        "change_rationale": question.get("change_rationale", "")[:600],
        "execution_status": row.get("status", "PENDING"),
        "observed_goal_outcome": outcome,
        "observed_primary_family": (row.get("attribution") or {}).get("primary_family"),
        "result": (
            "GOAL_FAILURE_NOT_OBSERVED"
            if outcome == "PASS"
            else "GOAL_FAILURE_OBSERVED_MECHANISM_UNCONFIRMED"
            if outcome == "FAIL"
            else "UNRESOLVED_NO_VALID_OUTCOME"
        ),
        "causal_assessment": "NOT_AUTOMATICALLY_ADJUDICATED",
    }


def failure_objective(memory, attempts, schema, evidence):
    records = [EpisodeRecord.model_validate(e["record"]) for e in memory["episodes"].values()]
    rules = rules_for_profile(profile_for_scene(schema))
    metrics = calculate_discovery_metrics(records, family_rules=rules)
    discovered = sorted({f for g in metrics["groups"] for f in g["discovered_families"]})
    successes = sum(r.task_outcome == "PASS" for r in records)
    failures = sum(r.task_outcome == "FAIL" for r in records)
    shown = [e["id"] for e in evidence if e["id"] in memory["episodes"]]
    recent_relief = any(
        a["candidate"].get("evidence", {}).get("intent") == "relief" for a in attempts[-3:]
    )
    relief_allowed = failures > 0 and not recent_relief
    intents = ["mechanism_transfer", "challenge"]
    if relief_allowed:
        intents = ["relief"] + intents if successes == 0 and failures >= 2 else intents + ["relief"]
    counts = Counter(a["candidate"].get("evidence", {}).get("target_family") for a in attempts)
    observations = []
    for ref in shown:
        row = memory["episodes"][ref]["record"]
        measures = row.get("measures") or {}
        observations.append(
            {
                "evidence_id": ref,
                "goal_outcome": row["task_outcome"],
                "robot_calls_used": row.get("robot_api_calls"),
                "sampled_behavior": {
                    k: measures.get(k)
                    for k in (
                        "sampled_progress_m",
                        "sampled_path_length_m",
                        "minimum_goal_distance_m",
                        "maximum_recorded_goal_dwell_s",
                        "minimum_base_height_m",
                        "maximum_base_tilt_deg",
                    )
                },
                "interpretation": (
                    "Observed numbers, not a diagnosed vulnerability or inferred failure"
                ),
            }
        )
    targets = [f for f in rules if f != "human_safety_risk" or schema == "clear-path-human-v5"]
    return {
        "version": "failure-directed-v2",
        "targets": {"fdr": 0.3, "distinct_measured_families": 4},
        "scope": (
            "Reviewed plus new comparable VALID episodes guide development selection; "
            "not evaluation denominator"
        ),
        "observed_pass": successes,
        "observed_fail": failures,
        "measured_discovered_families": discovered,
        "missing_supported_families": [f for f in targets if f not in discovered],
        "supported_targets": targets + ["unclassified"],
        "support_claim": "Operational rule support is not proof of attainable family scenarios",
        "target_attempt_counts": {f: counts[f] for f in targets + ["unclassified"]},
        "allowed_intents": intents,
        "intent_priority": intents,
        "behavior_evidence_ids": shown,
        "behavior_observations": observations,
        "recent_hypothesis_results": [prediction_review(a) for a in attempts[-4:] if "id" in a],
        "human_measurement_scope": (
            "Terminal sampled five seconds only; passing a human earlier may be outside this window"
        ),
        "pass_policy": (
            "PASS is valid evidence; never relabel it or penalize it as an execution error"
        ),
        "prediction_policy": (
            "Predicted family/risk is unconfirmed and NEVER used "
            "to assign actual outcome or coverage"
        ),
    }
