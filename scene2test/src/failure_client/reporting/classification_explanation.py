"""Display-only attribution explanations and saved AFS feedback inspection.

Neither function assigns a family, changes a verdict, nor supplies search feedback.
Episode counts deliberately do not replace the existing distinct-scene metric rules.
"""

import json
from collections import Counter, defaultdict

from llm_afs.behavior import digest

from .discovery_metrics import deduplicate_records

LABELS = {
    "primary_attributed": "주 실패 유형 있음",
    "multiple_detected_no_primary": "복합 징후 — 주 유형 보류",
    "no_supported_rule_detected": "지원 유형 미검출",
    "measurement_unknown": "측정 정보 불충분",
    "unverified_attribution": "유형 귀속 규칙 미검증",
    "unassigned_other": "기타 주 유형 미지정",
}


def classification_explanation(records, *, family_rules):
    """Explain each deduplicated valid FAIL without resolving ambiguous detections."""
    records, _ = deduplicate_records(records)
    groups = defaultdict(list)
    for record in records:
        if record.status != "VALID" or record.task_outcome != "FAIL":
            continue
        tax = record.taxonomy or {}
        family_rows = tax.get("families", {})
        detected = sorted(
            f for f in family_rules if family_rows.get(f, {}).get("status") == "DETECTED"
        )
        unknown = sorted(
            f
            for f in family_rules
            if family_rows.get(f, {}).get("status") not in {"DETECTED", "NOT_DETECTED"}
        )
        warnings = tax.get("warnings", [])
        primary = record.attribution
        if primary:
            category = (
                "primary_attributed"
                if family_rules.get(primary.primary_family) == primary.rule_version
                else "unverified_attribution"
            )
        elif len(detected) > 1 or any(
            w in warnings
            for w in ("ambiguous_multiple_families", "ambiguous_system_interface_families")
        ):
            category = "multiple_detected_no_primary"
        elif unknown or not family_rules:
            category = "measurement_unknown"
        elif not detected:
            category = "no_supported_rule_detected"
        else:
            category = "unassigned_other"
        groups[record.source.method, record.source.seed].append(
            {
                "evidence_id": record.evidence_id,
                "scene_id": record.scene_id,
                "source_path": record.source.path,
                "category": category,
                "label": LABELS[category],
                "primary_family": primary.primary_family if primary else None,
                "detected_families": detected,
                "unknown_supported_families": unknown,
                "warnings": warnings,
            }
        )

    def summary(rows):
        counts = Counter(r["category"] for r in rows)
        return {
            "valid_fail_episodes": len(rows),
            "counts": {k: counts[k] for k in LABELS},
            "episodes": rows,
        }

    methods = sorted({method for method, _ in groups})
    return {
        "version": "classification-explanation-v1",
        "labels": LABELS,
        "unit": "Deduplicated valid FAIL episodes, not distinct-scene diversity credit",
        "groups": [
            {"method": method, "seed": seed, **summary(rows)}
            for (method, seed), rows in sorted(groups.items())
        ],
        "pooled_by_method": {
            method: summary([r for (m, _), rows in groups.items() if m == method for r in rows])
            for method in methods
        },
        "claim": "Display-only: original metrics, attribution priority and ambiguity unchanged; "
        "diagnostic detections do not add discovered families or establish causes. "
        "Repeated-scene metric qualification can differ from these per-episode counts.",
    }


def saved_feedback_audit(context, request, response=None):
    """Verify saved context binding, then report supplied fields, not model comprehension."""
    content = (request.get("input") or [{}])[0].get("content")
    if not isinstance(content, str):
        return {"status": "UNSUPPORTED_REQUEST_LAYOUT", "claim": "Not treated as absent feedback"}
    payload = json.loads(content)
    if payload.get("context") != context or payload.get("context_sha256") != digest(context):
        raise ValueError("saved feedback request/context mismatch")
    objective = context.get("failure_objective", {})
    observations = objective.get("behavior_observations", [])
    trajectory = objective.get("trajectory_feedback", {})
    reviews = spaces = []
    response_status = "NOT_AVAILABLE"
    if response is not None:
        texts = [
            c["text"]
            for item in response.get("output", [])
            for c in item.get("content", [])
            if c.get("type") == "output_text"
        ]
        if len(texts) == 1:
            raw = json.loads(texts[0])
            if raw.get("context_sha256") != digest(context):
                raise ValueError("saved feedback response/context mismatch")
            reviews, spaces = raw.get("episode_reviews", []), raw.get("spaces", [])
            response_status = "CONTEXT_BOUND_STRUCTURED_RESPONSE"
        else:
            response_status = "STRUCTURED_TEXT_UNAVAILABLE"
    return {
        "status": "VERIFIED_SAVED_REQUEST_CONTEXT",
        "context_sha256": digest(context),
        "feedback_policy": objective.get("feedback_policy"),
        "observations": [
            {
                "evidence_id": o.get("evidence_id"),
                "blocked_navigation_count": o.get("action_diagnostics", {}).get(
                    "blocked_navigation_count"
                ),
                "action_diagnostics_supplied": bool(o.get("action_diagnostics")),
                "sampled_behavior_supplied": bool(o.get("sampled_behavior")),
                "detector_observations_supplied": bool(o.get("detector_observations")),
            }
            for o in observations
        ],
        "trajectory_summaries": trajectory.get("presented_episode_summaries", []),
        "cause_review_contract_supplied": bool(objective.get("cause_review_contract")),
        "response_status": response_status,
        "reviewed_evidence_ids": [r.get("evidence_id") for r in reviews],
        "candidate_targets": [s.get("target_family") for s in spaces],
        "claim": "Verified information supplied in saved request/response only; not proof of "
        "model comprehension, prose truth, causal reasoning quality or discovery improvement. "
        "This audit adds no feedback fields, model calls, labels or search-ranking changes.",
    }
