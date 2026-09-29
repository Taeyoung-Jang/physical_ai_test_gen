"""Pure goal-outcome statistics. Events, exclusions and repeated scenes are not hidden."""

from __future__ import annotations

from collections import Counter, defaultdict
from fractions import Fraction

from failure_client.evaluation.research_records import (
    FAMILIES,
    ComparisonDesign,
    EpisodeRecord,
)


def deduplicate_records(records):
    seen, paths, unique, duplicates = {}, {}, [], []
    for record in records:
        identity = record.evidence_id or "path:" + record.source.path
        path = record.source.path
        if path in paths and paths[path] != identity:
            raise ValueError("conflicting evidence for one source path")
        paths[path] = identity
        if identity in seen:
            previous = seen[identity]
            left = previous.model_dump(exclude={"source"})
            right = record.model_dump(exclude={"source"})
            left_assignment = previous.source.model_dump(exclude={"path"})
            right_assignment = record.source.model_dump(exclude={"path"})
            if left != right or left_assignment != right_assignment:
                raise ValueError("conflicting duplicate evidence or method/seed/stage assignment")
            duplicates.append({"source": path, "duplicate_of": previous.source.path})
            continue
        seen[identity] = record
        unique.append(record)
    return unique, duplicates


def _costs(records):
    fields = (
        "simulation_s",
        "robot_api_calls",
        "observed_input_tokens",
        "observed_output_tokens",
    )
    costs = {
        field: {
            "observed_total": sum(values) if values else None,
            "records_measured": len(values),
            "records_missing": len(records) - len(values),
        }
        for field in fields
        for values in [[getattr(r, field) for r in records if getattr(r, field) is not None]]
    }
    audits = [r.usage_audit for r in records if r.usage_audit]
    costs["token_usage_coverage"] = {
        "calls_with_usage": sum(r.calls_with_token_usage for r in records),
        "calls_missing_usage_observed": sum(a["calls_missing_usage"] for a in audits)
        if audits
        else None,
        "records_without_usage_audit": len(records) - len(audits),
        "records_partial": sum(a["status"] == "PARTIAL" for a in audits),
    }
    return costs


def _summary(records, family_rules):
    valid = [r for r in records if r.status == "VALID"]
    conditions = sorted({r.condition_id for r in valid})
    compatible = len(conditions) <= 1
    failures = [r for r in valid if r.task_outcome == "FAIL"]
    scenes = {r.scene_id for r in valid}
    failure_scenes = {r.scene_id for r in failures}
    labels = defaultdict(set)
    unsupported_attributions = 0
    for r in failures:
        if r.attribution:
            label = r.attribution
            if family_rules.get(label.primary_family) == label.rule_version:
                labels[r.scene_id].add(label.primary_family)
            else:
                unsupported_attributions += 1
    ambiguous = sorted(scene for scene, families in labels.items() if len(families) > 1)
    qualified = {
        scene: next(iter(families)) for scene, families in labels.items() if len(families) == 1
    }
    families = sorted(set(qualified.values()))
    measured = bool(family_rules) and compatible and bool(valid)
    operational = any(r.taxonomy for r in records)
    partial = (
        operational
        and measured
        and (len(family_rules) < len(FAMILIES) or any(not r.attribution for r in failures))
    )
    rate = len(failures) / len(valid) if valid and compatible else None
    curve, seen_failures, seen_scenes, seen_families = [], 0, set(), set()
    for index, r in enumerate(valid, 1):
        if r.task_outcome == "FAIL":
            seen_failures += 1
            seen_scenes.add(r.scene_id)
            if r.scene_id in qualified:
                seen_families.add(qualified[r.scene_id])
        curve.append(
            {
                "valid_rollouts": index,
                "failures": seen_failures,
                "unique_failure_scenes": len(seen_scenes),
                "discovered_family_count": len(seen_families) if measured else None,
            }
        )
    return {
        "attempts": len(records),
        "valid_rollouts": len(valid),
        "failures": len(failures),
        "successes": len(valid) - len(failures),
        "excluded_rollouts": len(records) - len(valid),
        "exclusion_counts": dict(
            Counter(r.exclusion_reason for r in records if r.status != "VALID")
        ),
        "condition_ids": conditions,
        "policy_origins": sorted({r.policy_origin for r in valid}),
        "conditions_compatible": compatible,
        "failure_discovery_rate": rate,
        "fdr_target_observed": rate >= 0.30 if rate is not None else None,
        "unique_scenes": len(scenes),
        "unique_failure_scenes": len(failure_scenes),
        "repeated_scene_failures": len(failures) - len(failure_scenes),
        "valid_stage_counts": dict(Counter(r.source.stage for r in valid)),
        "discovered_families": families if measured else [],
        "discovered_family_count": len(families) if measured else None,
        "failure_diversity_coverage": len(families) / 6 if measured and not partial else None,
        "observed_family_coverage_lower_bound": len(families) / 6 if measured else None,
        "diversity_target_observed": (
            True if measured and len(families) >= 4 else False if measured and not partial else None
        ),
        "coverage_status": "partial_operational_rules"
        if partial
        else "measured"
        if measured
        else ("incompatible_conditions" if not compatible else "not_measured"),
        "family_status": {
            f: (
                "DISCOVERED"
                if f in families
                else "UNKNOWN"
                if operational
                and any(
                    r.taxonomy.get("families", {}).get(f, {}).get("status") in {None, "UNKNOWN"}
                    or "ambiguous_multiple_families" in r.taxonomy.get("warnings", [])
                    for r in failures
                )
                else "NOT_DISCOVERED"
            )
            if f in family_rules and compatible
            else "UNSUPPORTED"
            for f in FAMILIES
        },
        "ambiguous_family_scenes": ambiguous,
        "unverified_attributions": unsupported_attributions,
        "unclassified_failures": sum(r.scene_id not in qualified for r in failures),
        "costs": _costs(records),
        "curve_input_order": curve if compatible else [],
    }


def _gain(afs, random):
    if not afs["valid_rollouts"] or not random["valid_rollouts"]:
        return {"status": "no_valid_rollouts", "relative_gain": None, "gain_target_observed": None}
    a = Fraction(afs["failures"], afs["valid_rollouts"])
    r = Fraction(random["failures"], random["valid_rollouts"])
    gain = (a - r) / r if r else None
    return {
        "status": "measured" if gain is not None else "baseline_zero",
        "relative_gain": float(gain) if gain is not None else None,
        "difference_percentage_points": float(100 * (a - r)),
        "failure_count_difference": afs["failures"] - random["failures"],
        "gain_target_observed": gain >= Fraction(1, 5) if gain is not None else None,
    }


def calculate_discovery_metrics(
    records: list[EpisodeRecord],
    design: ComparisonDesign | None = None,
    *,
    family_rules: dict[str, str] | None = None,
):
    """family_rules is an in-process detector registry, never a proposal's self-reported label."""
    family_rules = family_rules or {}
    if not set(family_rules) <= set(FAMILIES) or any(
        not isinstance(v, str) or not v for v in family_rules.values()
    ):
        raise ValueError("invalid family detector registry")
    if design:
        design = ComparisonDesign.model_validate(design.model_dump())
    # Revalidate even when a caller used pydantic.model_copy(update=...) without validation.
    records = [EpisodeRecord.model_validate(r.model_dump()) for r in records]
    records, duplicates = deduplicate_records(records)
    buckets = defaultdict(list)
    for r in records:
        buckets[r.source.method, r.source.seed].append(r)
    if design:
        for method in ("afs", "random"):
            for seed in design.seeds:
                buckets[method, seed]
    groups = []
    for (method, seed), rows in sorted(buckets.items()):
        summary = _summary(rows, family_rules)
        budget = design.valid_budget_per_seed if design else None
        n = summary["valid_rollouts"]
        groups.append(
            {
                "method": method,
                "seed": seed,
                "valid_budget": budget,
                "budget_status": "undeclared"
                if budget is None
                else ("complete" if n == budget else "incomplete" if n < budget else "over_budget"),
                **summary,
            }
        )
    pooled = {
        method: _summary([r for r in records if r.source.method == method], family_rules)
        for method in sorted({g["method"] for g in groups})
    }
    comparison = {
        "status": "missing_comparison_design",
        "relative_gain": None,
        "gain_target_observed": None,
        "per_seed": [],
    }
    if design:
        issues = []
        if any(
            g["method"] not in {"afs", "random"} or g["seed"] not in design.seeds for g in groups
        ):
            issues.append("unexpected_method_or_seed")
        if any(g["budget_status"] != "complete" for g in groups):
            issues.append("unequal_or_incomplete_valid_budget")
        if any(r.condition_id != design.condition_id for r in records if r.status == "VALID"):
            issues.append("condition_mismatch")
        if any(
            r.status == "VALID" and r.policy_origin == "openai_api" and not r.returned_models
            for r in records
        ):
            issues.append("missing_returned_model_identity")
        if issues:
            comparison.update(status="not_comparable", issues=issues)
        else:
            lookup = {(g["method"], g["seed"]): g for g in groups}
            comparison = {
                **_gain(pooled["afs"], pooled["random"]),
                "per_seed": [
                    {"seed": seed, **_gain(lookup["afs", seed], lookup["random", seed])}
                    for seed in design.seeds
                ],
            }
    return {
        "schema_version": "failure-discovery-metrics-v1",
        "targets": {"fdr": 0.30, "relative_gain": 0.20, "families": 4, "family_denominator": 6},
        "design": design.model_dump() if design else None,
        "input_records": len(records) + len(duplicates),
        "unique_records": len(records),
        "duplicate_records": duplicates,
        "groups": groups,
        "pooled_by_method": pooled,
        "comparison": comparison,
        "supported_family_rules": family_rules,
        "limitations": [
            "Descriptive imported-data measurements, not an audited prospective benchmark",
            "Method/seed/stage and domain/distribution are supplied labels, not inferred from logs",
            "All valid cold starts, repeats and boundary probes consume the declared budget",
            "Pooled family union uses all seeds; it is not coverage at a single seed's budget",
            "Curve follows input order; chronology must be supplied by a campaign ledger",
            "Point targets are not statistical superiority; no confidence interval computed",
            "AFS API cost and full wall time unavailable; token costs may be partial",
            "Mock results test wiring only; not real robot/model performance",
        ],
    }
