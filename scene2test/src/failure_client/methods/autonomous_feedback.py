"""Bounded development selection; axis diversity is not failure-family coverage."""

from copy import deepcopy
from typing import Literal

from pydantic import Field, model_validator

from failure_client.evaluation.research_records import StrictRecord
from failure_client.methods.behavior_feedback import (
    boundary_candidate,
    choose_probe,
    feedback_context,
    parameters,
    repeat_candidate,
)
from llm_afs import behavior as b


class SearchBudget(StrictRecord):
    schema_version: Literal["autonomous-afs-budget-v1"] = "autonomous-afs-budget-v1"
    max_attempts: int = Field(default=6, ge=1, le=72)
    max_afs_requests: int = Field(default=6, ge=1, le=72)
    max_attempts_per_axis: int = Field(default=2, ge=1, le=16)
    max_repeats: int = Field(default=1, ge=0, le=4)
    history_limit: int = Field(default=4, ge=2, le=8)
    afs_model: str = Field(default="gpt-6-luna", min_length=1)
    afs_timeout_s: float = Field(default=300.0, gt=0, le=600)
    selection_policy: Literal["alternating-v1", "discovery-v1", "failure-directed-v2"] = (
        "alternating-v1"
    )
    valid_rollout_target: int | None = Field(default=None, ge=1, le=60)
    min_axis_change_fraction: float = Field(default=0.1, gt=0, le=1)

    @model_validator(mode="after")
    def check_target(self):
        if (
            self.selection_policy == "alternating-v1"
            and max(self.max_attempts, self.max_afs_requests) > 16
        ):
            raise ValueError("legacy alternating budgets remain limited to 16")
        if self.valid_rollout_target is not None:
            if self.selection_policy not in {"discovery-v1", "failure-directed-v2"}:
                raise ValueError("valid target requires a discovery policy")
            if self.valid_rollout_target > self.max_attempts:
                raise ValueError("valid target exceeds attempt cap")
        return self


def accounting(attempts, axes, budget):
    counts = {axis: sum(a["candidate"]["axis"] == axis for a in attempts) for axis in axes}
    last = next(
        (a["candidate"]["axis"] for a in reversed(attempts) if a["candidate"]["axis"] is not None),
        None,
    )
    blocked = {
        axis: "axis_attempt_budget"
        if count >= budget.max_attempts_per_axis
        else "previous_probe_axis_cooldown"
        for axis, count in counts.items()
        if count >= budget.max_attempts_per_axis or axis == last
    }
    return {
        "axis_attempts": counts,
        "blocked_axes": blocked,
        "selectable_axes": [a for a in axes if a not in blocked],
        "repeats": sum(a["candidate"]["stage"] == "repeat" for a in attempts),
    }


def bind(candidate, memory):
    """Resolve a concrete verified anchor and ensure only one parameter can change."""
    candidate = deepcopy(candidate)
    if candidate["stage"] == "repeat":
        anchor = candidate["evidence"]["case_id"]
    elif candidate["stage"] == "boundary":
        anchor = candidate["evidence"]["low"]["case_ids"][0]
    else:
        anchor = candidate["selection_audit"]["anchor_case_id"]
    case = next(c for c in memory["cases"] if c["case_id"] == anchor)
    base = parameters(case)
    target = candidate["parameters"]
    if set(target) != set(base):
        raise ValueError("candidate scene domain mismatch")
    changed = [k for k in base if target[k] != base[k]]
    if len(changed) != (0 if candidate["stage"] == "repeat" else 1):
        raise ValueError("expected an explicit repeat or exactly one changed scene parameter")
    candidate.update(anchor_case_id=anchor, axis=changed[0] if changed else None)
    return candidate


def selection(memory, attempts, budget, schema):
    """LLM first; at most one local step between LLM hypotheses; no local starvation."""
    axes = list(parameters(memory["cases"][0]))
    audit = accounting(attempts, axes, budget)
    discovery = budget.selection_policy in {"discovery-v1", "failure-directed-v2"}
    if budget.selection_policy == "discovery-v1" and audit["selectable_axes"]:
        least = min(audit["axis_attempts"][a] for a in audit["selectable_axes"])
        audit["selectable_axes"] = [
            a for a in audit["selectable_axes"] if audit["axis_attempts"][a] == least
        ]
    local_slot = not discovery and bool(attempts) and len(attempts) % 2 == 1
    audit.update(slot="local" if local_slot else "hypothesis", local_rejections=[])
    if local_slot:
        repeat = repeat_candidate(memory, mixed_only=True)
        if repeat is not None:
            if audit["repeats"] < budget.max_repeats:
                candidate = bind(repeat, memory)
                candidate["scheduler"] = audit
                return candidate, None
            audit["local_rejections"].append("mixed_repeat_budget_exhausted")
        # Exclude axes BEFORE selecting the narrowest bracket so one exhausted
        # bracket cannot mask other eligible brackets.
        filtered = {
            **memory,
            "brackets": [r for r in memory["brackets"] if r["axis"] in audit["selectable_axes"]],
        }
        midpoint = boundary_candidate(filtered)
        if midpoint is not None:
            candidate = bind(midpoint, memory)
            candidate["scheduler"] = audit
            return candidate, None
        audit["local_rejections"].append("no_eligible_unobserved_bracket")
    if not audit["selectable_axes"]:
        return None, None
    ctx = feedback_context(
        memory,
        history_limit=budget.history_limit,
        remaining=budget.max_attempts - len(attempts),
        scene_schema=schema,
    )
    ctx["development_search"] = {
        "mode": "autonomous-development-v1",
        "external_history": True,
        "benchmark_comparison": False,
        "attempt_budget_not_valid_sample_target": budget.valid_rollout_target is None,
        "selection_policy": budget.selection_policy,
        "min_axis_change_fraction": budget.min_axis_change_fraction if discovery else 0,
        "budget": budget.model_dump(),
        **audit,
    }
    if discovery:
        ctx["search_selection"].update(
            policy="hypothesis-v2",
            mode_priority=["cross_mechanism", "success_probe", "boundary_probe"],
        )
    if budget.selection_policy == "failure-directed-v2":
        from failure_client.methods.failure_objective import failure_objective

        new_valid = sum(a.get("episode", {}).get("status") == "VALID" for a in attempts)
        remaining_target = (
            max(0, budget.valid_rollout_target - new_valid)
            if budget.valid_rollout_target is not None
            else None
        )
        ctx["remaining_valid_budget"] = remaining_target
        ctx["development_search"].update(
            remaining_attempts=budget.max_attempts - len(attempts),
            remaining_valid_target=remaining_target,
        )
        ctx["failure_objective"] = failure_objective(
            memory, attempts, schema, ctx["latest"]["evidence"]
        )
        ctx["search_selection"].update(
            policy="failure-directed-v2",
            ranking=(
                "intent, missing measured family, target attempts, "
                "axis attempts, proposal order, novelty"
            ),
        )
    return None, ctx


def selected_probe(raw, ctx, memory):
    # Validate every space, not only the eventual winning endpoint. Preserve the
    # original response: do not silently discard an out-of-quota proposal.
    proposal = b.endpoint_proposal(raw, ctx)
    b.validate(proposal, ctx)
    if any(s.axis not in ctx["development_search"]["selectable_axes"] for s in proposal.spaces):
        raise ValueError("proposal uses a cooled-down or exhausted axis")
    if "failure_objective" in ctx:
        objective = ctx["failure_objective"]
        for space in proposal.spaces:
            if not set(space.behavior_refs) <= set(objective["behavior_evidence_ids"]):
                raise ValueError("failure hypothesis requires supplied episode behavior evidence")
            if not set(space.behavior_refs) <= set(space.evidence_refs):
                raise ValueError("behavior references must also be declared evidence references")
            if space.intent not in objective["allowed_intents"]:
                raise ValueError("relief requires comparable FAIL evidence and relief cooldown")
            if space.target_family not in objective["supported_targets"]:
                raise ValueError("target family is unsupported in this domain")
            if space.mode != ("success_probe" if space.intent == "relief" else "cross_mechanism"):
                raise ValueError("proposal mode contradicts failure-search intent")
    candidate = bind(choose_probe(raw, ctx, memory), memory)
    candidate["scheduler"] = ctx["development_search"]
    return candidate
