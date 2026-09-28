"""Descriptive search milestones; no new goal verdicts or failure-family labels."""

from collections import defaultdict

from failure_client.archive.regression_cases import _brackets
from failure_client.methods.search_evidence import SIGNATURE_VERSION, behavior_signature
from failure_client.reporting.discovery_metrics import _costs, deduplicate_records


def search_diagnostics(memory, records):
    records, _ = deduplicate_records(records)
    lookup = {eid: case for case in memory["cases"] for eid in case["episodes"]}
    groups = defaultdict(list)
    for record in records:
        groups[record.source.method, record.source.seed].append(record)
    result = []
    for (method, seed), rows in sorted(groups.items()):
        valid_rows = [r for r in rows if r.status == "VALID"]
        if len({r.condition_id for r in valid_rows}) > 1:
            result.append({"method": method, "seed": seed, "status": "incompatible_conditions"})
            continue
        prefix, seen_patterns, curve = {}, set(), []
        unknown_patterns = failures = valid = 0
        first_success = first_bracket = None
        brackets = []
        for index, row in enumerate(rows):
            if row.status != "VALID":
                continue
            valid += 1
            case = lookup[row.evidence_id]
            current = prefix.setdefault(
                case["case_id"],
                {
                    **case,
                    "episodes": [],
                    "pass_count": 0,
                    "fail_count": 0,
                },
            )
            current["episodes"].append(row.evidence_id)
            current["pass_count" if row.task_outcome == "PASS" else "fail_count"] += 1
            brackets = _brackets(list(prefix.values()))
            milestone = {
                "valid_rollouts": valid,
                "attempts": index + 1,
                "costs_through_attempt": _costs(rows[: index + 1]),
            }
            if row.task_outcome == "PASS" and first_success is None:
                first_success = milestone
            if brackets and first_bracket is None:
                first_bracket = milestone
            if row.task_outcome == "FAIL":
                failures += 1
                signature = behavior_signature(memory["episodes"][row.evidence_id])
                if signature["id"] is None:
                    unknown_patterns += 1
                else:
                    seen_patterns.add(signature["id"])
            curve.append(
                {
                    "valid_rollouts": valid,
                    "failures": failures,
                    "distinct_failure_patterns": len(seen_patterns),
                    "failures_without_pattern": unknown_patterns,
                    "observed_brackets": len(brackets),
                    "minimum_normalized_bracket_width": min(
                        (b["normalized_width"] for b in brackets), default=None
                    ),
                }
            )
        known = failures - unknown_patterns
        result.append(
            {
                "method": method,
                "seed": seed,
                "status": "measured" if valid else "no_valid_rollouts",
                "first_observed_success": first_success,
                "first_observed_bracket": first_bracket,
                "failures_with_pattern": known,
                "failures_without_pattern": unknown_patterns,
                "distinct_failure_patterns": len(seen_patterns),
                "repeated_pattern_fraction": (known - len(seen_patterns)) / known
                if known
                else None,
                "current_observed_brackets": brackets,
                "mixed_cases": [
                    {
                        "case_id": c["case_id"],
                        "passes": c["pass_count"],
                        "failures": c["fail_count"],
                    }
                    for c in prefix.values()
                    if c["pass_count"] and c["fail_count"]
                ],
                "curve": curve,
            }
        )
    return {
        "schema_version": "afs-search-diagnostics-v1",
        "pattern_version": SIGNATURE_VERSION,
        "groups": result,
        "limits": [
            "Patterns are heuristic behavior similarity, NOT the six failure families or causes",
            "Mixed repeats can remove an observed bracket; no deterministic boundary claim",
            "Milestones include robot costs; AFS request costs remain in campaign_execution",
            "Null milestones are not observed, not zero; curves follow recorded attempt order",
            "FDR/Gain and goal outcome definitions are unchanged",
        ],
    }


def experiment_reviews(attempts, memory):
    """Join each selected question to measurements; do not auto-judge free-text causes."""
    rows = []
    for attempt in attempts:
        candidate = attempt["candidate"]
        audit = candidate.get("selection_audit")
        if audit is None:
            continue
        anchor = memory["episodes"].get(audit.get("anchor_evidence_id"), {}).get("record")
        episode = attempt.get("episode")
        after = (episode or {}).get("measures") or {}
        before = (anchor or {}).get("measures") or {}
        progress_change = None
        if (
            episode
            and episode["status"] == "VALID"
            and all(m.get("last_sample_goal_distance_m") is not None for m in (before, after))
        ):
            progress_change = (
                before["last_sample_goal_distance_m"] - after["last_sample_goal_distance_m"]
            )
        rows.append(
            {
                "attempt_id": attempt["id"],
                "method": attempt["method"],
                "seed": attempt["seed"],
                "hypothesis_id": audit["hypothesis_id"],
                "question": candidate["evidence"],
                "anchor_evidence_id": audit.get("anchor_evidence_id"),
                "episode_evidence_id": (episode or {}).get("evidence_id"),
                "anchor_outcome": (anchor or {}).get("task_outcome"),
                "observed_outcome": (episode or {}).get("task_outcome"),
                "execution_status": (episode or {}).get("status", "PENDING"),
                "final_goal_distance_reduction_vs_anchor_m": progress_change,
                "causal_assessment": "NOT_AUTOMATICALLY_ADJUDICATED",
            }
        )
    return rows
