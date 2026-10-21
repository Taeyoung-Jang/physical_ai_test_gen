"""Explicit execution allocation, not a failure oracle or random fallback."""

from collections import Counter

GROUP_ORDER = ("floor_physics", "object_physics", "obstacle_geometry", "layout", "human")
FORMS = ("small", "large", "combination")
LARGE_FRACTION = 0.3


def group(axis):
    if axis == "floor_friction":
        return "floor_physics"
    if axis in {"box_mass_kg", "box_friction"}:
        return "object_physics"
    if axis.startswith("human_"):
        return "human"
    if axis.startswith("obstacle_") and any(t in axis for t in ("size_", "height", "yaw")):
        return "obstacle_geometry"
    return "layout"


def candidate_axes(candidate):
    return candidate.get("changed_axes") or (
        [candidate["axis"]] if candidate.get("axis") is not None else []
    )


def groups(candidate):
    return sorted({group(a) for a in candidate_axes(candidate)})


def behavior_relevance(memory):
    """Allocation evidence, NOT physical engagement, a verdict or causal relevance."""
    from .trajectory_feedback import trajectory

    observed, absent, unknown = [], [], []
    for entry in memory.get("episodes", {}).values():
        record = entry["record"]
        if record.get("status") != "VALID" or record.get("task_outcome") not in {"PASS", "FAIL"}:
            continue
        summary = trajectory(entry, {})
        ref = record["evidence_id"]
        if summary["manipulation_results"]:
            observed.append(ref)
        elif summary["patterns"]["no_manipulation_request"] is True:
            absent.append(ref)
        else:
            unknown.append(ref)
    state = (
        "REQUEST_OBSERVED"
        if observed
        else "NO_REQUEST_OBSERVED"
        if absent and not unknown
        else "UNKNOWN"
    )
    return {
        "version": "behavior-relevance-v1",
        "object_physics": {
            "status": state,
            "request_evidence_ids": sorted(observed),
            "complete_without_request_evidence_ids": sorted(absent),
            "unknown_evidence_ids": sorted(unknown),
        },
        "claim": (
            "Verified supplied VALID memory only; absent requests do not prove physical "
            "irrelevance. Requests, including rejection, do not prove physical engagement."
        ),
    }


def allocation(attempts, selectable, *, relevance=None):
    counts = Counter(g for a in attempts for g in groups(a["candidate"]))
    recent = []
    for a in reversed(attempts):
        e = a.get("episode") or {}
        if e.get("status") != "VALID" or e.get("task_outcome") != "PASS":
            break
        recent.append(a["candidate"])
    paused_groups, paused_families = [], []
    if len(recent) >= 2:
        paused_groups = sorted(set(groups(recent[0])) & set(groups(recent[1])))
        f = recent[0]["evidence"].get("target_family")
        if f and f == recent[1]["evidence"].get("target_family"):
            paused_families = [f]
    available = [g for g in GROUP_ORDER if any(group(a) == g for a in selectable)]
    deferred = (
        ["object_physics"]
        if relevance is not None and relevance["object_physics"]["status"] == "NO_REQUEST_OBSERVED"
        else []
    )
    mandatory = [g for g in available if g not in deferred]
    eligible = [g for g in mandatory if g not in paused_groups] or mandatory
    target = min(eligible, key=lambda g: (counts[g], GROUP_ORDER.index(g))) if eligible else None
    result = {
        "version": "breadth-v1" if relevance is None else "behavior-relevance-v1",
        "group_axes": {g: [a for a in selectable if group(a) == g] for g in GROUP_ORDER},
        "group_attempts": {g: counts[g] for g in GROUP_ORDER},
        "required_group": target,
        "required_form": FORMS[len(attempts) % len(FORMS)],
        "large_change_fraction": LARGE_FRACTION,
        "paused_after_two_passes": {"groups": paused_groups, "predicted_families": paused_families},
        "accounting": (
            "New attempt intents, including exclusions; combinations charge both groups/axes"
        ),
        "claim": "Execution allocation is not measured failure-family coverage",
    }
    if relevance is not None:
        result.update(
            behavior_relevance=relevance,
            mandatory_groups=mandatory,
            deferred_mandatory_groups=deferred,
            optional_exploration_groups=[g for g in available if g in deferred],
            deferred_group_policy=(
                "Not removed from allowed/selectable axes. May accompany another required "
                "group in a combination; if no mandatory group remains, no group is forced. "
                "Unknown action evidence retains balanced allocation."
            ),
        )
    return result


def describe(changes, base, axes):
    fractions = {a: abs(v - base[a]) / (axes[a][1] - axes[a][0]) for a, v in changes}
    return {
        "changed_axes": [a for a, _ in changes],
        "groups": sorted({group(a) for a, _ in changes}),
        "normalized_changes": fractions,
        "form": "combination"
        if len(changes) == 2
        else ("large" if max(fractions.values()) + 1e-12 >= LARGE_FRACTION else "small"),
    }


def reject(features, evidence, contract):
    if features["form"] != contract["required_form"]:
        return "allocation_form_mismatch"
    if (
        contract["required_group"] is not None
        and contract["required_group"] not in features["groups"]
    ):
        return "allocation_group_mismatch"
    if features["form"] == "combination" and len(features["groups"]) != 2:
        return "combination_requires_two_factor_groups"
    paused = contract["paused_after_two_passes"]
    if evidence["target_family"] in paused["predicted_families"]:
        return "repeated_pass_hypothesis_switch_required"
    return None


def rank(candidate, objective, contract):
    evidence = candidate["evidence"]
    family = evidence["target_family"]
    features = candidate["exploration"]
    return (
        family in objective["missing_supported_families"],
        -objective["intent_priority"].index(evidence["intent"]),
        -objective["target_attempt_counts"].get(family, 0),
        -sum(contract["group_attempts"][g] for g in features["groups"]),
        candidate["novelty"],
        -candidate["space_index"],
    )
