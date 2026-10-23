"""Measured coverage and bounded failure-seeking priorities; not a failure oracle."""

from collections import Counter

from failure_client.evaluation.research_records import EpisodeRecord
from failure_client.evaluation.taxonomy_profiles import metric_options
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics


def prediction_review(attempt):
    question = attempt["candidate"].get("evidence", {})
    row = attempt.get("episode") or {}
    outcome = row.get("task_outcome") if row.get("status") == "VALID" else None
    return {
        "attempt_id": attempt["id"],
        "axis": attempt["candidate"].get("axis"),
        **(
            {"branch_audit": attempt["candidate"]["branch_audit"]}
            if "branch_audit" in attempt["candidate"]
            else {}
        ),
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


def failure_objective(
    memory,
    attempts,
    schema,
    evidence,
    *,
    taxonomy_profile="scene-default",
    feedback_policy="legacy",
    anchor_policy="pass-control-v3",
    pattern_feedback="off",
):
    records = [EpisodeRecord.model_validate(e["record"]) for e in memory["episodes"].values()]
    options = metric_options(schema, taxonomy_profile)
    rules = options["family_rules"]
    metrics = calculate_discovery_metrics(records, **options)
    discovered = sorted({f for g in metrics["groups"] for f in g["discovered_families"]})
    successes = sum(r.task_outcome == "PASS" for r in records)
    failures = sum(r.task_outcome == "FAIL" for r in records)
    shown = [e["id"] for e in evidence if e["id"] in memory["episodes"]]
    behavior_attempts = (
        [a for a in attempts if a.get("episode", {}).get("status") == "VALID"]
        if anchor_policy == "failure-diversity-v4"
        else attempts
    )
    recent_relief = any(
        a["candidate"].get("evidence", {}).get("intent") == "relief" for a in behavior_attempts[-3:]
    )
    relief_allowed = failures > 0 and not recent_relief
    intents = ["mechanism_transfer", "challenge"]
    if relief_allowed:
        intents = (
            ["relief"] + intents
            if successes == 0 and failures >= 2 and anchor_policy != "failure-diversity-v4"
            else intents + ["relief"]
        )
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
        if taxonomy_profile == "expanded-ten-v1":
            taxonomy = row.get("taxonomy") or {}
            expanded = taxonomy.get("measurements", {}).get("expanded_behavior", {})
            observations[-1]["measured_types"] = {
                "primary": (row.get("attribution") or {}).get("primary_family"),
                "diagnostic_only": taxonomy.get("diagnostic_families", []),
                "statuses": {f: v.get("status") for f, v in taxonomy.get("families", {}).items()},
                "goal_completion": expanded.get("goal_completion_failure"),
                "fall": expanded.get("fall"),
                "manipulation": expanded.get("manipulation_failure"),
                "stall_execution_windows": expanded.get("locomotion_stall"),
            }
    targets = [f for f in rules if f != "human_safety_risk" or schema == "clear-path-human-v5"]
    objective = {
        "version": "failure-directed-v2",
        "anchor_policy": anchor_policy,
        "behavior_cooldown_scope": "valid_episodes_only"
        if anchor_policy == "failure-diversity-v4"
        else "attempt_intents",
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
    if taxonomy_profile == "expanded-ten-v1":
        from failure_client.evaluation.expanded_taxonomy import PRIORITY, THRESHOLDS

        objective.update(
            taxonomy_profile=taxonomy_profile,
            family_inventory=list(options["family_inventory"]),
            family_denominator=10,
            operational_thresholds=dict(THRESHOLDS),
            primary_counting_priority=list(PRIORITY),
            classification_limits=(
                "One primary per failed episode; secondary diagnoses are not extra discoveries. "
                "Goal completion failure requires final inside-region but short dwell; "
                "not every budget stop. Manipulation rejection is not physical incapacity. "
                "Stall uses actual execution, not inference or intentional stop/turn. "
                "Operational observations are not established causes."
            ),
        )
    if feedback_policy in {"action-diagnostics-v1", "cause-review-v2", "cause-review-v3"}:
        from .action_diagnostics import action_diagnostics

        current_ids = {
            a.get("episode", {}).get("evidence_id")
            for a in attempts
            if a.get("episode", {}).get("evidence_id")
        }

        def coverage(rows):
            measured = calculate_discovery_metrics(rows, **options)
            return sorted({f for g in measured["groups"] for f in g["discovered_families"]})

        current = coverage([r for r in records if r.evidence_id in current_ids])
        historical = coverage([r for r in records if r.evidence_id not in current_ids])
        objective.update(
            feedback_policy=feedback_policy,
            coverage_priority_scope="new_session_attempts_only",
            historical_discovered_families=historical,
            cumulative_discovered_families=discovered,
            current_discovered_families=current,
            measured_discovered_families=current,
            missing_supported_families=[f for f in targets if f not in current],
        )
        goal = memory["cases"][0]["task_contract"]["goal"]
        diagnostics = {ref: action_diagnostics(memory["episodes"][ref], goal) for ref in shown}
        for observation in observations:
            observation["action_diagnostics"] = diagnostics[observation["evidence_id"]]
        for review in objective["recent_hypothesis_results"]:
            attempt = next(a for a in attempts if a["id"] == review["attempt_id"])
            ref = (attempt.get("episode") or {}).get("evidence_id")
            if ref in memory["episodes"]:
                review["action_diagnostics"] = action_diagnostics(memory["episodes"][ref], goal)
        objective["action_diagnostic_scope"] = (
            "Whole episode diagnostics are separate from terminal-window family rules; "
            "no new labels, causal attribution, robot commands or metric credit"
        )
        pattern_counts = {"historical": Counter(), "current": Counter()}
        for ref, entry in memory["episodes"].items():
            row = entry["record"]
            if row["status"] != "VALID" or row["task_outcome"] != "FAIL":
                continue
            d = action_diagnostics(entry, goal)
            bucket = pattern_counts[
                "current" if row["evidence_id"] in current_ids else "historical"
            ]
            if d.get("blocked_navigation_count", 0):
                bucket["failed_with_blocked_navigation"] += 1
            if d.get("staging_arrivals_outside_goal"):
                bucket["failed_after_staging_arrival_outside_goal"] += 1
            if d.get("manipulation_engagement") == "NO_TOOL_REQUEST_OBSERVED":
                bucket["failed_without_manipulation_request"] += 1
        objective["action_pattern_feedback"] = {
            "historical_failure_episode_counts": dict(pattern_counts["historical"]),
            "current_failure_episode_counts": dict(pattern_counts["current"]),
            "scope": "Overlapping descriptive episode counts, NOT distinct types or causes",
            "guidance": (
                "When the same current-set pattern recurs, propose alternatives with a "
                "different expected action sequence using admissible anchors/scene axes. "
                "Explain why the intended mechanism should be exercised; do not force actions."
            ),
        }
        if feedback_policy in {"cause-review-v2", "cause-review-v3"}:
            from .cause_review import review_contract

            objective["cause_review_contract"] = review_contract(ctx_evidence=evidence, rules=rules)
            for observation in observations:
                row = memory["episodes"][observation["evidence_id"]]["record"]
                measured = row.get("taxonomy", {}).get("measurements", {})
                contacts = measured.get("non_support_contacts", {})
                recent_contacts = contacts.get("terminal_navigation_contacts")
                blocked = measured.get("blocked_tools")
                observation["detector_observations"] = {
                    "terminal_progress": measured.get("terminal_progress"),
                    "recent_blocked_tools": len(blocked) if blocked is not None else None,
                    "qualifying_recent_contacts": (
                        len(recent_contacts) if recent_contacts is not None else None
                    ),
                    "geometry": measured.get("geometry"),
                    "human_proximity_contract": measured.get("human_proximity", {}).get("contract"),
                    "claim": "Existing measured gates; unknown stays unknown, not LLM labels",
                }
        if feedback_policy == "cause-review-v3":
            from failure_client.evaluation.discovery_readiness import audit_discovery

            objective["domain_constraints"] = audit_discovery(schema)["human_goal_compatibility"]
    if pattern_feedback == "trajectory-v1":
        from .trajectory_feedback import feedback

        objective["trajectory_feedback"] = feedback(memory, attempts, shown)
    return objective
