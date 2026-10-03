"""Local goal-agent method adapter, not an HTTP registry plugin.

Reuses CandidateObservation, behavior-AFS schema/context binding and P1 measurements.
Only environment values are emitted; the policy still chooses every robot action.
"""

from __future__ import annotations

import random

from clear_path.contracts import parse_fixture
from clear_path.fixture import graph
from clear_path.scene_space import axes_for_parameters, axes_for_schema
from failure_client.methods.base import CandidateObservation
from failure_client.methods.search_evidence import behavior_signature, compact_evidence
from llm_afs import behavior as b
from llm_afs.behavior_request import request


def seeded(seed, *parts):
    return random.Random(int(b.digest([seed, *parts]), 16))


def uniform_scene(seed, *parts, schema="clear-path-fixture-v1"):
    rng = seeded(seed, *parts)
    return {k: rng.uniform(*bounds) for k, bounds in axes_for_schema(schema).items()}


def parameters(case):
    return {k: case["parameters"][k] for k in axes_for_parameters(case["parameters"])}


def distance(a, c, axes=None):
    axes = axes or b.AXES
    if set(a) != set(axes) or set(c) != set(axes):
        raise ValueError("distance requires the same complete scene domain")
    return max(abs(a[k] - c[k]) / (hi - lo) for k, (lo, hi) in axes.items())


def search_state(memory):
    cases = memory["cases"]
    if any(c["role"] == "mixed_outcomes" for c in cases):
        return "mixed_outcomes"
    if not any(c["pass_count"] for c in cases):
        return "no_success_control"
    if memory["brackets"]:
        return "observed_bracket"
    return "seek_alternative"


def similar_failures(memory, base, axes):
    latest = next(reversed(memory["episodes"].values()))
    pattern = behavior_signature(latest)
    if latest["record"]["task_outcome"] != "FAIL" or pattern["id"] is None:
        return 0
    return sum(
        entry["record"]["task_outcome"] == "FAIL"
        and behavior_signature(entry)["id"] == pattern["id"]
        for c in memory["cases"]
        if distance(parameters(c), base, axes) <= 0.05
        for entry in (memory["episodes"][eid] for eid in c["episodes"])
    )


def feedback_context(
    memory,
    *,
    history_limit,
    remaining,
    scene_schema="clear-path-fixture-v1",
    selection_policy="hypothesis-v2",
):
    if selection_policy not in ("novelty-v1", "hypothesis-v2"):
        raise ValueError("unknown campaign selection policy")
    cases = memory["cases"]
    if not cases or any(c["parameters"] is None for c in cases):
        raise ValueError("verified scene evidence required")
    axes = axes_for_schema(scene_schema)
    if any(c["parameters"].get("schema_version") != scene_schema for c in cases):
        raise ValueError("feedback must use the frozen scene schema")
    episodes = list(memory["episodes"].values())
    if len({c["condition_id"] for c in cases}) != 1:
        raise ValueError("feedback must use one robot/task/budget condition")
    latest = episodes[-1]
    # Keep latest, a PASS, a FAIL, then recent observations; disclose every omission.
    selected = [latest]
    for outcome in ("PASS", "FAIL"):
        row = next((e for e in reversed(episodes) if e["record"]["task_outcome"] == outcome), None)
        if row is not None and row not in selected:
            selected.append(row)
    for row in reversed(episodes):
        if len(selected) >= history_limit:
            break
        if row not in selected:
            selected.append(row)
    evidence = []
    for entry in selected[:history_limit]:
        record, behavior = entry["record"], entry["behavior"]
        evidence.append(
            {
                "id": record["evidence_id"],
                "outcome": record["task_outcome"],
                "scene_id": record["scene_id"],
                "measures": record["measures"],
                "components": behavior["components"],
                "object_motion": behavior["object_motion"],
                **compact_evidence(entry),
                "behavior_pattern": behavior_signature(entry),
                "warnings": behavior["warnings"],
            }
        )
    compact_cases = [
        {
            k: c[k]
            for k in (
                "case_id",
                "scene_id",
                "parameters",
                "pass_count",
                "fail_count",
                "role",
                "primary_family",
                "causal_status",
            )
        }
        for c in cases
    ]
    evidence.extend(
        [
            {"id": "case_memory", "measurement": compact_cases},
            {"id": "observed_brackets", "measurement": memory["brackets"]},
        ]
    )
    latest_case = next(c for c in cases if latest["record"]["evidence_id"] in c["episodes"])
    state = search_state(memory)
    stagnant = similar_failures(memory, parameters(latest_case), axes)
    modes = (
        ["success_probe", "cross_mechanism", "boundary_probe"]
        if state == "no_success_control"
        else ["cross_mechanism", "success_probe", "boundary_probe"]
    )
    if stagnant >= 3:
        modes = ["cross_mechanism", "success_probe", "boundary_probe"]
    return {
        "schema_version": "behavior-campaign-feedback-v1",
        "latest": {"parameters": parameters(latest_case), "evidence": evidence},
        "scene_graph": graph(parse_fixture(latest_case["parameters"])),
        "task_contract": latest_case["task_contract"],
        "robot_condition": latest_case["reproduction"],
        "allowed_axes": axes,
        "search_selection": {
            "policy": selection_policy,
            "state": state,
            "anchor_case_id": latest_case["case_id"],
            "anchor_evidence_id": latest["record"]["evidence_id"],
            "mode_priority": modes,
            "similar_nearby_failures": stagnant,
            "cooldown_threshold": 3,
            "cooldown_normalized_distance": 0.05,
            "ranking": "purpose, proposal order, endpoint novelty"
            if selection_policy == "hypothesis-v2"
            else "endpoint novelty",
            "claim": "Heuristic priority, not calibrated failure probability or causal attribution",
        },
        "remaining_valid_budget": remaining,
        "history_selection": {
            "total": len(episodes),
            "selected": len(evidence) - 2,
            "limit": history_limit,
            "other_arm_data_used": False,
        },
        "limitations": [
            "Events are not causes or goal failures; unsupported telemetry is not zero",
            "Only supplied validated taxonomy evidence supports family labels; "
            "unsupported types and behavior patterns are not discovered coverage",
            "Only P1 observed_brackets may support a boundary claim; mixed repeats stay uncertain",
            "SceneGraph legacy push_goal/contact annotations are not task requirements",
            "Do not keep amplifying a failing setting; test success side and alternative axes",
            "Inference is included in observation windows, not an exact action timestamp",
        ],
    }


def proposal_request(ctx, model):
    policy = ctx.get("search_selection", {}).get("policy", "novelty-v1")
    return request(
        ctx,
        model,
        selection_policy=(
            "campaign_hypothesis_endpoint"
            if policy == "hypothesis-v2"
            else "campaign_single_endpoint"
        ),
    )


def choose_probe(raw, ctx, memory):
    proposal = b.Proposal.model_validate(raw)
    b.validate(proposal, ctx)
    axes = b.context_axes(ctx)
    base = ctx["latest"]["parameters"]
    seen = [parameters(c) for c in memory["cases"]]
    stagnant = similar_failures(memory, base, axes)
    options, rejected = [], []
    for index, space in enumerate(proposal.spaces):
        for value in (space.low, space.high):
            params = {**base, space.axis: value}
            if any(distance(params, old, axes) < 1e-8 for old in seen):
                rejected.append({"space": index, "value": value, "reason": "already_observed"})
                continue
            if stagnant >= 3 and distance(params, base, axes) <= 0.05:
                rejected.append(
                    {"space": index, "value": value, "reason": "similar_failure_cooldown"}
                )
                continue
            options.append(
                {
                    "parameters": params,
                    "strategy": space.mode,
                    "stage": "discovery",
                    "evidence": space.model_dump(),
                    "boundary_confirmed": False,
                    "space_index": index,
                    "novelty": min(distance(params, old, axes) for old in seen),
                }
            )
    if not options:
        raise ValueError("proposal has no novel non-cooled-down endpoint; no automatic fallback")
    selection = ctx.get("search_selection", {})
    policy = selection.get("policy", "novelty-v1")
    if policy == "hypothesis-v2":
        modes = selection["mode_priority"]
        chosen = max(
            options, key=lambda c: (-modes.index(c["strategy"]), -c["space_index"], c["novelty"])
        )
    elif policy == "novelty-v1":
        chosen = max(options, key=lambda c: c["novelty"])
    else:
        raise ValueError("unknown campaign selection policy")
    chosen["selection_audit"] = {
        **selection,
        "rejected": rejected,
        "eligible": [
            {k: c[k] for k in ("space_index", "strategy", "parameters", "novelty")} for c in options
        ],
        "hypothesis_id": b.digest([ctx, chosen["space_index"], chosen["evidence"]]),
        "selected_mode": chosen["strategy"],
        "modes_without_eligible_candidate": [
            mode
            for mode in selection.get("mode_priority", [])
            if not any(c["strategy"] == mode for c in options)
        ],
        "interpretation": "Untested endpoints and causal claims remain unconfirmed",
    }
    return chosen


def repeat_candidate(memory, *, desired="observed_failure", mixed_only=False):
    mixed = [c for c in memory["cases"] if c["role"] == "mixed_outcomes"]
    choices = mixed or ([] if mixed_only else [c for c in memory["cases"] if c["role"] == desired])
    if mixed_only and not choices:
        return None
    case = min(choices or memory["cases"], key=lambda c: len(c["episodes"]))
    return {
        "parameters": parameters(case),
        "strategy": "mixed_outcome_repeat" if mixed else "control_repeat",
        "stage": "repeat",
        "evidence": {"case_id": case["case_id"]},
    }


def boundary_candidate(memory):
    lookup = {c["case_id"]: c for c in memory["cases"]}
    seen = [parameters(c) for c in memory["cases"]]
    for bracket in sorted(memory["brackets"], key=lambda b: b["normalized_width"]):
        case = lookup[bracket["low"]["case_ids"][0]]
        axes = axes_for_parameters(case["parameters"])
        base = parameters(case)
        params = {**base, bracket["axis"]: bracket["midpoint_probe"]}
        if not any(distance(params, old, axes) < 1e-8 for old in seen):
            return {
                "parameters": params,
                "strategy": "observed_boundary_midpoint",
                "stage": "boundary",
                "evidence": bracket,
            }
    return None


class BehaviorMethodState:
    """Small observe/checkpoint adapter; checkpoint is committed with the measured episode."""

    def __init__(self, state=None):
        self.observed = dict((state or {}).get("observed", {}))

    def observe(self, observations: list[CandidateObservation]):
        for obs in observations:
            data = obs.model_dump(mode="json")
            if obs.candidate_id in self.observed and self.observed[obs.candidate_id] != data:
                raise ValueError("conflicting observation replay")
            self.observed[obs.candidate_id] = data

    def state_dict(self):
        return {"observed": self.observed}

    def load_state_dict(self, state):
        self.observed = dict(state["observed"])
