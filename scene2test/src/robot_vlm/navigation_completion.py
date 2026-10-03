"""Versioned robot-local arrival handling; never adds time or assigns a verdict."""

import math

PROFILES = ("position_only_v1", "goal_dwell_v1")
DEFAULT = "position_only_v1"
TARGET_RADIUS_M = 0.12


def completion_contract(profile=DEFAULT):
    if profile not in PROFILES:
        raise ValueError("unknown navigation completion profile")
    return {
        "profile": profile,
        "target_radius_m": TARGET_RADIUS_M,
        "final_goal_target_tolerance_m": 1e-6,
        "final_goal_arrival": (
            "return_immediately"
            if profile == DEFAULT
            else "hold_within_requested_action_until_goal_or_deadline"
        ),
        "intermediate_arrival": "return_immediately",
        "extra_calls": 0,
        "extra_action_time_s": 0,
        "post_budget_grace_s": 0,
    }


def profile_from_protocol(protocol):
    """Old archives mean position-only; new declarations must match the full contract."""
    if "navigation_completion" not in protocol:
        return DEFAULT
    value = protocol["navigation_completion"]
    if not isinstance(value, dict) or value != completion_contract(value.get("profile")):
        raise ValueError("invalid navigation completion contract")
    return value["profile"]


class NavigationCompletion:
    def __init__(self, profile, target, goal):
        contract = completion_contract(profile)
        self.target = target
        self.goal = goal
        self.hold_for_goal = (
            profile == "goal_dwell_v1"
            and math.dist(target, goal["target_xy_m"]) <= contract["final_goal_target_tolerance_m"]
        )
        self.anchor = None
        self.anchor_yaw = None
        self.first_arrival_s = None
        self.hold_steps = 0

    def mode(self, time_s, base, heading):
        """Return follow/hold/return. Goal success stays with the independent evaluator."""
        if self.anchor is not None:
            if math.dist(base[:2], self.goal["target_xy_m"]) < self.goal["radius_m"]:
                self.hold_steps += 1
                return "hold"
            # A drift out of the goal region cancels the hold; the existing follower
            # can try again within the SAME action deadline. Dwell resets in evaluator.
            self.anchor = self.anchor_yaw = None
        if math.dist(base[:2], self.target) < TARGET_RADIUS_M:
            if self.first_arrival_s is None:
                self.first_arrival_s = float(time_s)
            if not self.hold_for_goal:
                return "return"
            self.anchor = list(base)
            self.anchor_yaw = heading
            self.hold_steps += 1
            return "hold"
        return "follow"

    def audit(self, dt):
        return {
            "goal_dwell_enabled_for_target": self.hold_for_goal,
            "first_target_arrival_s": self.first_arrival_s,
            "hold_simulation_s": self.hold_steps * dt,
        }
