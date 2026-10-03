"""Measured action-only motion; not a goal verdict or a semantic plan interpreter."""

import math

VERSION = "action-motion-v1"


class MotionFeedback:
    def __init__(self, action, time_s, base, heading, goal):
        self.action = action
        self.start_s = float(time_s)
        self.start = list(base[:2])
        self.last = list(base[:2])
        self.start_heading = float(heading)
        self.goal = goal
        self.samples = 0
        self.path_length = 0.0
        self.command_sum = [0.0, 0.0, 0.0]
        self.yaw_limited = 0
        self.blocked = 0

    def observe(self, base, command, navigation=None):
        self.path_length += math.dist(base[:2], self.last)
        self.last = list(base[:2])
        self.samples += 1
        for i, value in enumerate(command):
            self.command_sum[i] += value
        self.yaw_limited += abs(command[2]) >= 0.4 - 1e-9
        self.blocked += bool(navigation and navigation["status"] == "blocked_connector")

    def result(self, time_s, base, heading):
        end = list(base[:2])
        delta = [end[i] - self.start[i] for i in (0, 1)]
        c, s = math.cos(self.start_heading), math.sin(self.start_heading)
        raw = (
            [self.action.vx_mps, self.action.vy_mps, self.action.yaw_rate_rps]
            if self.action.action == "move"
            else None
        )
        return {
            "version": VERSION,
            "window": "execution only; excludes preceding inference hold",
            "start_simulation_s": self.start_s,
            "end_simulation_s": float(time_s),
            "elapsed_s": float(time_s) - self.start_s,
            "start_xy_m": self.start,
            "end_xy_m": end,
            "delta_world_xy_m": delta,
            "delta_start_body_xy_m": [c * delta[0] + s * delta[1], -s * delta[0] + c * delta[1]],
            "net_translation_m": math.dist(self.start, end),
            "sampled_base_path_length_m": self.path_length,
            "path_length_note": "includes gait oscillations, not useful route progress",
            "yaw_change_rad": math.atan2(
                math.sin(heading - self.start_heading), math.cos(heading - self.start_heading)
            ),
            "goal_distance_reduction_m": math.dist(self.start, self.goal)
            - math.dist(end, self.goal),
            "raw_move_command_body": raw,
            "commanded_stationary": raw == [0.0, 0.0, 0.0] if raw is not None else None,
            "samples": self.samples,
            "mean_command_body": [v / self.samples for v in self.command_sum]
            if self.samples
            else None,
            "yaw_limit_fraction": self.yaw_limited / self.samples if self.samples else None,
            "blocked_connector_samples": self.blocked,
            "causality": "measured execution, not a failure cause or action recommendation",
        }


def policy_feedback(memory, heading):
    """Small prominent summary; no invented measurements for old/missing feedback."""
    zeros = 0
    for row in reversed(memory):
        motion = row["execution"].get("motion", {})
        if row["action"]["action"] != "move" or motion.get("commanded_stationary") is not True:
            break
        zeros += 1
    c, s = math.cos(heading), math.sin(heading)
    return {
        "version": VERSION,
        "recent_consecutive_zero_move_commands": zeros,
        "count_window": "retained last 8 decisions; stale/unmeasured actions break the streak",
        "last_motion": memory[-1]["execution"].get("motion") if memory else None,
        "body_forward_world_xy": [c, s],
        "body_left_world_xy": [-s, c],
        "semantics": "Only numeric command fields actuate the robot; plan_summary is not executed. "
        "All-zero move requests zero velocity (physical drift may still occur). "
        "observe uses pose hold. Choose actions yourself from measured feedback.",
    }
