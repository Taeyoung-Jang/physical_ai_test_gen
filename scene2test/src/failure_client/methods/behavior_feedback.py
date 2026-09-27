"""Local goal-agent method adapter, not an HTTP registry plugin.

Reuses CandidateObservation, behavior-AFS schema/context binding and P1 measurements.
Only environment values are emitted; the policy still chooses every robot action.
"""

from __future__ import annotations

import random

from clear_path.contracts import Fixture
from clear_path.fixture import graph
from failure_client.methods.base import CandidateObservation
from llm_afs import behavior as b
from llm_afs.behavior_request import request


def seeded(seed, *parts):
    return random.Random(int(b.digest([seed, *parts]), 16))


def uniform_scene(seed, *parts):
    rng = seeded(seed, *parts)
    return {k: rng.uniform(*bounds) for k, bounds in b.AXES.items()}


def parameters(case):
    return {k: case["parameters"][k] for k in b.AXES}


def distance(a, c):
    return max(abs(a[k] - c[k]) / (hi - lo) for k, (lo, hi) in b.AXES.items())


def feedback_context(memory, *, history_limit, remaining):
    cases = memory["cases"]
    if not cases or any(c["parameters"] is None for c in cases):
        raise ValueError("verified three-axis scene evidence required")
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
        intervals = [i for i in behavior["intervals"] if not i["details"].get("support_contact")]
        evidence.append(
            {
                "id": record["evidence_id"],
                "outcome": record["task_outcome"],
                "scene_id": record["scene_id"],
                "measures": record["measures"],
                "components": behavior["components"],
                "object_motion": behavior["object_motion"],
                "intervals": intervals[:12],
                "interval_count": len(intervals),
                "display_limit": 12,
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
    return {
        "schema_version": "behavior-campaign-feedback-v1",
        "latest": {"parameters": parameters(latest_case), "evidence": evidence},
        "scene_graph": graph(Fixture(**parameters(latest_case))),
        "task_contract": latest_case["task_contract"],
        "robot_condition": latest_case["reproduction"],
        "allowed_axes": b.AXES,
        "remaining_valid_budget": remaining,
        "history_selection": {
            "total": len(episodes),
            "selected": len(evidence) - 2,
            "limit": history_limit,
            "other_arm_data_used": False,
        },
        "limitations": [
            "Events are not causes or goal failures; unsupported telemetry is not zero",
            "No failure family detectors; diversity cannot currently be measured",
            "Only P1 observed_brackets may support a boundary claim; mixed repeats stay uncertain",
            "SceneGraph legacy push_goal/contact annotations are not task requirements",
            "Do not keep amplifying a failing setting; test success side and alternative axes",
            "Inference is included in observation windows, not an exact action timestamp",
        ],
    }


def proposal_request(ctx, model):
    return request(ctx, model, selection_policy="campaign_single_endpoint")


def choose_probe(raw, ctx, memory):
    proposal = b.Proposal.model_validate(raw)
    b.validate(proposal, ctx)
    base = ctx["latest"]["parameters"]
    seen = [parameters(c) for c in memory["cases"]]
    # Three nearby failures with the same recorded action/event summary trigger cooldown.
    episodes = list(memory["episodes"].values())
    latest = episodes[-1]["record"]

    def signature(record):
        m = record["measures"] or {}
        return b.digest(
            [record["termination_reason"], m.get("action_counts"), m.get("event_counts")]
        )

    stagnant = 0
    for case in memory["cases"]:
        if distance(parameters(case), base) <= 0.05:
            stagnant += sum(
                memory["episodes"][eid]["record"]["task_outcome"] == "FAIL"
                and signature(memory["episodes"][eid]["record"]) == signature(latest)
                for eid in case["episodes"]
            )
    options = []
    for space in proposal.spaces:
        for value in (space.low, space.high):
            params = {**base, space.axis: value}
            if any(distance(params, old) < 1e-8 for old in seen):
                continue
            if stagnant >= 3 and distance(params, base) <= 0.05:
                continue
            options.append(
                {
                    "parameters": params,
                    "strategy": space.mode,
                    "stage": "discovery",
                    "evidence": space.model_dump(),
                    "boundary_confirmed": False,
                }
            )
    if not options:
        raise ValueError("proposal has no novel non-cooled-down endpoint; no automatic fallback")
    return max(options, key=lambda c: min(distance(c["parameters"], old) for old in seen))


def boundary_candidate(memory):
    lookup = {c["case_id"]: c for c in memory["cases"]}
    seen = [parameters(c) for c in memory["cases"]]
    for bracket in sorted(memory["brackets"], key=lambda b: b["normalized_width"]):
        base = parameters(lookup[bracket["low"]["case_ids"][0]])
        params = {**base, bracket["axis"]: bracket["midpoint_probe"]}
        if not any(distance(params, old) < 1e-8 for old in seen):
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
