"""Explicit observed PASS/FAIL branches; mixed/excluded scenes are never anchors."""

from clear_path.contracts import parse_fixture
from clear_path.fixture import graph
from failure_client.methods.behavior_feedback import parameters


def allowed_anchor_roles(intent, ctx):
    v4 = ctx["failure_objective"].get("anchor_policy") == "failure-diversity-v4"
    if intent == "relief":
        return {"observed_failure"}
    if intent == "mechanism_transfer" and v4:
        return {"success_control", "observed_failure"}
    return {"success_control"}


def branch_catalog(memory, ctx):
    shown = set(ctx["failure_objective"]["behavior_evidence_ids"])
    catalog = []
    for case in memory["cases"]:
        if case["role"] not in {"success_control", "observed_failure"}:
            continue
        refs = [ref for ref in case["episodes"] if ref in shown]
        if refs:
            catalog.append(
                {
                    "case_id": case["case_id"],
                    "role": case["role"],
                    "observed_outcome": "PASS" if case["role"] == "success_control" else "FAIL",
                    "parameters": parameters(case),
                    "evidence_ids": refs,
                    "scene_graph": graph(parse_fixture(case["parameters"])),
                }
            )
    catalog.sort(key=lambda c: c["case_id"])
    if not catalog:
        raise ValueError("no unmixed observed PASS/FAIL anchor with supplied behavior evidence")
    objective = ctx["failure_objective"]
    roles = {c["role"] for c in catalog}
    allowed = [i for i in objective["allowed_intents"] if allowed_anchor_roles(i, ctx) & roles]
    if not allowed:
        raise ValueError("no eligible branch: an observed PASS control may be required")
    objective.update(
        allowed_intents=allowed,
        intent_priority=[i for i in objective["intent_priority"] if i in allowed],
    )
    ctx["anchor_catalog"] = catalog
    # Explicit tabulation avoids relying on comparing every full scene in prose.
    # Include observed cases even when their detailed behavior is outside history_limit;
    # these are already present in case_memory, not newly invented behavior evidence.
    ctx["observed_single_axis_endpoints"] = [
        {
            "anchor_case_id": anchor["case_id"],
            "axis": changed[0],
            "value": old[changed[0]],
            "matching_case_id": case["case_id"],
            "observed_role": case["role"],
        }
        for anchor in catalog
        for case in memory["cases"]
        for old in [parameters(case)]
        for changed in [[k for k, v in anchor["parameters"].items() if old[k] != v]]
        if len(changed) == 1
    ]
    ctx["branch_contract"] = {
        "version": "failure-branch-v3",
        "challenge_and_transfer": "unmixed observed PASS anchor",
        "relief": "unmixed observed FAIL anchor",
        "latest_is": "latest observation, NOT implicit candidate base",
        "derived_coordinates": (
            "width may remap coordinates; one parameter is not one geometry edit"
        ),
        "claim": "Separate recorded branches, not causal proof or guaranteed independence",
    }
    if objective.get("anchor_policy") == "failure-diversity-v4":
        ctx["branch_contract"].update(
            anchor_policy="failure-diversity-v4",
            challenge_and_transfer="challenge: PASS; mechanism_transfer: PASS or FAIL",
            challenge="unmixed observed PASS anchor",
            mechanism_transfer=(
                "unmixed observed PASS or FAIL anchor; different behavior hypothesis"
            ),
            cooldown_scope="VALID behavior only; all intents still consume quotas and costs",
        )
        for anchor in catalog:
            anchor["allowed_intents"] = [
                i for i in allowed if anchor["role"] in allowed_anchor_roles(i, ctx)
            ]


def checked_anchor(space, ctx):
    anchor = next((c for c in ctx["anchor_catalog"] if c["case_id"] == space.anchor_case_id), None)
    if anchor is None:
        raise ValueError("unknown, mixed, excluded or unpresented anchor")
    if anchor["role"] not in allowed_anchor_roles(space.intent, ctx):
        raise ValueError("new-mechanism/challenge requires PASS; relief requires FAIL")
    declared = getattr(space, "anchor_behavior_refs", space.behavior_refs)
    if hasattr(space, "anchor_behavior_refs") and (
        not set(declared) <= set(anchor["evidence_ids"])
        or not set(declared) <= set(space.evidence_refs)
        or len(set(declared)) != len(declared)
    ):
        raise ValueError(
            "anchor_behavior_refs must name selected anchor evidence and evidence_refs"
        )
    refs = [r for r in declared if r in anchor["evidence_ids"]]
    if not refs:
        raise ValueError("proposal must cite actual behavior from its selected anchor")
    return anchor, refs[0]
