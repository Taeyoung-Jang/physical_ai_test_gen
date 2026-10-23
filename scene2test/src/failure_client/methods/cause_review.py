"""Evidence-bound LLM reviews and detector guidance, NOT causal adjudication."""

from failure_client.evaluation.expanded_taxonomy import THRESHOLDS as EXPANDED_THRESHOLDS
from failure_client.evaluation.failure_taxonomy import THRESHOLDS


def review_contract(*, ctx_evidence, rules):
    episodes = [e for e in ctx_evidence if e.get("outcome") in {"PASS", "FAIL"}]
    required = [episodes[0]["id"]] if episodes else []
    failed = next((e["id"] for e in episodes if e["outcome"] == "FAIL"), None)
    if failed and failed not in required:
        required.append(failed)
    definitions = {
        "collision": {
            "requires": (
                "Terminal stalled AND qualifying known non-box world contact "
                "during navigate_to/move"
            ),
            "excludes": [
                "clear_floor",
                "clear_box_geom",
                "box-only contact",
                "contact with PASS",
                "no_path alone",
            ],
            "thresholds": {
                k: THRESHOLDS[k]
                for k in ("contact_duration_s", "contact_force_n", "recent_contact_s")
            },
        },
        "obstacle_interference": {
            "requires": (
                "Terminal stalled AND at least two accepted plan_path/navigate_to "
                "no_path/blocked_endpoint results in recent window AND nearby obstacle"
            ),
            "excludes": [
                "earlier block outside window",
                "one blocked result",
                "no_tracking_clearance alone",
                "global unreachability inference",
            ],
            "thresholds": {
                k: THRESHOLDS[k]
                for k in ("blocked_tool_window_s", "blocked_tool_count", "near_obstacle_m")
            },
        },
        "goal_occupied": {
            "requires": (
                "Terminal stalled AND same verified upright ground object covers "
                "the ENTIRE task goal disk throughout terminal window"
            ),
            "excludes": ["partial overlap", "planner inflation alone", "object near goal alone"],
        },
        "human_safety_risk": {
            "requires": (
                "Verified scene-bound human/base traces AND sustained exposure in terminal "
                "five seconds AND goal FAIL; use supplied human proximity contract radii/duration"
            ),
            "excludes": [
                "earlier exposure outside terminal window",
                "PASS exposure as failure",
                "static proxy without verified trace",
                "causal or real-world safety certification",
            ],
        },
        "fall": {
            "requires": "Complete sampled pose trace with sustained low base height OR high tilt",
            "excludes": ["brief tilt", "missing pose samples", "predicted instability"],
            "thresholds": {
                k: EXPANDED_THRESHOLDS[k]
                for k in ("fall_height_m", "fall_tilt_deg", "fall_sustained_s", "max_state_gap_s")
            },
        },
        "locomotion_stall": {
            "requires": (
                "Recent navigate_to/move actual execution with enough duration, "
                "low translation and low excursion; complete execution samples"
            ),
            "excludes": [
                "inference wait",
                "intentional stop/turn",
                "target_reached",
                "goal_reached",
                "short rejected planner call",
            ],
            "thresholds": {
                k: EXPANDED_THRESHOLDS[k]
                for k in (
                    "stall_recent_s",
                    "stall_execution_s",
                    "stall_translation_m",
                    "stall_excursion_m",
                )
            },
        },
        "manipulation_failure": {
            "requires": (
                "Last accepted push/pick/place tool result per object failed/rejected/aborted; "
                "a later success supersedes it"
            ),
            "excludes": [
                "no manipulation request",
                "mass/friction change alone",
                "proof of physical pushing incapacity",
            ],
        },
        "goal_completion_failure": {
            "requires": (
                "Final full-rate task state INSIDE goal region with incomplete "
                "required dwell and goal not reached"
            ),
            "excludes": [
                "final pose outside region",
                "every BUDGET_EXHAUSTED",
                "minimum distance earlier in episode",
            ],
        },
    }
    return {
        "version": "cause-review-v2",
        "required_evidence_ids": required,
        "terminal_stalled_contract": {
            k: THRESHOLDS[k]
            for k in (
                "terminal_window_s",
                "max_state_gap_s",
                "max_goal_distance_range_m",
                "max_base_excursion_m",
            )
        },
        "terminal_stalled_requires": (
            "Complete terminal window; all sampled distances outside task goal radius, "
            "limited distance range and base excursion"
        ),
        "detectors": {f: {"rule_version": rules[f], **definitions[f]} for f in rules},
        "unsupported": ["unreachable", "perception_error"],
        "claim": (
            "Guidance mirrors fixed operational rules; LLM hypotheses never assign verdicts/types"
        ),
    }


def validate_reviews(proposal, ctx):
    objective = ctx["failure_objective"]
    evidence = {
        e["id"]: e
        for e in ctx["latest"]["evidence"]
        if e["id"] in objective["behavior_evidence_ids"]
    }
    reviews = {r.evidence_id: r for r in proposal.episode_reviews}
    if len(reviews) != len(proposal.episode_reviews):
        raise ValueError("duplicate reviewed evidence")
    if not set(objective["cause_review_contract"]["required_evidence_ids"]) <= set(reviews):
        raise ValueError("missing required episode review")
    for ref, review in reviews.items():
        if ref not in evidence:
            raise ValueError("episode review requires presented behavior evidence")
        e = evidence[ref]
        if review.observed_outcome != e["outcome"]:
            raise ValueError("episode review changed observed outcome")
        versions = {a.get("observation_version") for a in e.get("action_timeline", [])}
        if (
            len(set(review.observation_versions)) != len(review.observation_versions)
            or not set(review.observation_versions) <= versions
        ):
            raise ValueError("episode review cites unknown or duplicate action version")
    for space in proposal.spaces:
        ref = space.analysis_evidence_id
        if ref not in reviews or ref not in space.behavior_refs or ref not in space.evidence_refs:
            raise ValueError("candidate must cite a reviewed episode in behavior/evidence refs")


def plan_conflict(space):
    """Only an explicit logical contradiction, not NLP truth checking or risk scoring."""
    if space.target_family == "collision" and space.measurement_plan.expected_contact_scope in {
        "box_only",
        "not_applicable",
    }:
        return "collision_plan_excludes_qualifying_world_contact"
    return None
