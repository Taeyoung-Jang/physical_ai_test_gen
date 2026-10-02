"""Goal-only task contract. Process termination is not a behavioral failure label."""

import hashlib
import json
import math

PROFILES = ("goal_outcome_v1", "legacy_guarded")
GUARD_REASONS = {"FALL", "FORBIDDEN_CONTACT", "CONTACT_FORCE_LIMIT", "SKILL_RELEASE_FAILURE"}
BUDGET_REASONS = {"BUDGET_EXHAUSTED", "SIMULATION_BUDGET", "INFERENCE_SIM_BUDGET"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def task_contract(goal_xy, max_calls, max_seconds, profile="goal_outcome_v1"):
    if profile not in PROFILES:
        raise ValueError("unknown evaluation profile")
    return {
        "schema_version": "task-goal-v1",
        "task_id": "reach_destination",
        "goal": {
            "entity": "robot_base",
            "frame": "world_m",
            "target_xy_m": list(goal_xy),
            "radius_m": 0.25,
            "dwell_s": 1.0,
        },
        "evaluation_profile": profile,
        "episode_budget": {
            "max_robot_policy_calls": max_calls,
            "max_simulation_s": max_seconds,
            "inference_wait_counts_as_simulation_time": True,
        },
    }


class GoalEvaluator:
    def __init__(self, contract):
        self.contract = contract
        self.reached_since = None
        self.goal_reached = False

    def observe(self, time_s, xy):
        goal = self.contract["goal"]
        if math.dist(xy, goal["target_xy_m"]) < goal["radius_m"]:
            if self.reached_since is None:
                self.reached_since = time_s
            if time_s - self.reached_since >= goal["dwell_s"] - 1e-9:
                self.goal_reached = True
        else:
            self.reached_since = None
        return self.goal_reached

    def progress(self, time_s, xy):
        """Read-only diagnostics, not a second evaluator or a success prediction."""
        goal = self.contract["goal"]
        distance = math.dist(xy, goal["target_xy_m"])
        distance = distance if math.isfinite(distance) else None
        inside = None if distance is None else distance < goal["radius_m"]
        dwell = (
            None
            if inside is None
            else max(0.0, time_s - self.reached_since)
            if inside and self.reached_since is not None
            else 0.0
        )
        return {
            "distance_m": distance,
            "radius_m": goal["radius_m"],
            "inside_goal_region": inside,
            "required_dwell_s": goal["dwell_s"],
            "current_dwell_s": dwell,
            "remaining_dwell_s": None if dwell is None else max(0.0, goal["dwell_s"] - dwell),
            "goal_reached": self.goal_reached,
        }

    def result(self, reason, valid):
        profile = self.contract["evaluation_profile"]
        if not valid:
            outcome, actor = "INCONCLUSIVE", "infrastructure"
        elif self.goal_reached:
            outcome, actor = "PASS", "goal_evaluator"
        elif reason in BUDGET_REASONS:
            outcome, actor = "FAIL", "episode_budget"
        elif reason == "POLICY_STOP":
            outcome, actor = "FAIL", "robot"
        else:
            # Legacy guards truncate the goal-only counterfactual; do not relabel them.
            outcome = "INCONCLUSIVE"
            actor = "legacy_guard" if reason in GUARD_REASONS else "supervisor"
        return {
            "schema_version": "task-outcome-v1",
            "evaluation_profile": profile,
            "task_contract_sha256": digest(self.contract),
            "task_outcome": outcome,
            "goal_reached": None if outcome == "INCONCLUSIVE" else self.goal_reached,
            "termination": {"actor": actor, "reason": reason},
            "execution_valid": valid,
            "valid_execution": valid,  # compatibility, NOT sufficient for an AFS label
            "success": outcome == "PASS",
        }
