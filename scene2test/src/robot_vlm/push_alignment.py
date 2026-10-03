"""Bounded robot-internal alignment, never a scene/task-specific approach plan."""

import math

import numpy as np

from .push_skill import (
    MAX_PUSH_DISTANCE_M,
    MIN_PUSH_DISTANCE_M,
    PUSH_DISTANCE_ABS_TOLERANCE_M,
    angle_error,
    supported_push_distance,
)

VERSION = "push-alignment-v1"
MAX_SECONDS = 8.0


def readiness(base, yaw, box, box_yaw, size, target):
    delta = np.asarray(target) - np.asarray(box)[:2]
    distance = float(np.linalg.norm(delta))
    heading = math.atan2(delta[1], delta[0])
    f = np.array([math.cos(heading), math.sin(heading)])
    side = np.array([-f[1], f[0]])
    gap = np.asarray(box)[:2] - np.asarray(base)[:2]
    values = {
        "forward_gap_m": float(gap @ f),
        "lateral_error_m": float(gap @ side),
        "heading_error_rad": angle_error(heading, yaw),
        "box_face_error_rad": angle_error(heading, box_yaw),
        "push_distance_m": distance,
        "base_height_m": float(base[2]),
        "box_height_m": float(box[2]),
        "push_heading_rad": heading,
    }
    checks = {
        "forward_gap": 0.72 <= values["forward_gap_m"] <= 0.90,
        "lateral": abs(values["lateral_error_m"]) <= 0.06,
        "heading": abs(values["heading_error_rad"]) <= 0.12,
        "box_face": abs(values["box_face_error_rad"]) <= 0.12,
        "distance": supported_push_distance(distance),
        "height": 0.65 <= base[2] <= 0.85 and 0.30 <= box[2] <= 0.40,
        "geometry": bool(np.allclose(size, [0.8, 1.1, 0.7], atol=0.001)),
        "finite": bool(np.isfinite([*values.values(), *size]).all()),
    }
    checks = {k: bool(v) for k, v in checks.items()}
    limits = {
        "forward_gap_m": [0.72, 0.90],
        "lateral_error_abs_m": 0.06,
        "heading_error_abs_rad": 0.12,
        "box_face_error_abs_rad": 0.12,
        "push_distance_m": [MIN_PUSH_DISTANCE_M, MAX_PUSH_DISTANCE_M],
        "push_distance_abs_tolerance_m": PUSH_DISTANCE_ABS_TOLERANCE_M,
        "base_height_m": [0.65, 0.85],
        "box_height_m": [0.30, 0.40],
        "box_size_m": [0.8, 1.1, 0.7],
    }
    correctable = (
        all(v for k, v in checks.items() if k not in {"forward_gap", "lateral", "heading"})
        and 0.72 <= values["forward_gap_m"] <= 0.98
        and abs(values["lateral_error_m"]) <= 0.14
        and abs(values["heading_error_rad"]) <= 0.20
    )
    return {
        "measured": values,
        "limits": limits,
        "checks": checks,
        "ready": all(checks.values()),
        "correctable": bool(correctable),
    }


class Alignment:
    def __init__(self, base, yaw):
        self.previous = np.asarray(base)[:2].copy()
        self.yaw_start = yaw
        self.travel = 0.0
        self.ready_since = None

    def update(self, elapsed, base, yaw, state):
        self.travel += float(np.linalg.norm(np.asarray(base)[:2] - self.previous))
        self.previous = np.asarray(base)[:2].copy()
        if not state["correctable"]:
            return "alignment_out_of_range", [0.0, 0.0, 0.0]
        if self.travel > 0.20 or abs(angle_error(yaw, self.yaw_start)) > 0.25:
            return "alignment_motion_limit", [0.0, 0.0, 0.0]
        if elapsed >= MAX_SECONDS:
            return "alignment_timeout", [0.0, 0.0, 0.0]
        m = state["measured"]
        stable = (
            state["ready"]
            and abs(m["lateral_error_m"]) <= 0.03
            and abs(m["heading_error_rad"]) <= 0.06
        )
        self.ready_since = (
            (elapsed if self.ready_since is None else self.ready_since) if stable else None
        )
        if self.ready_since is not None and elapsed - self.ready_since >= 0.25:
            return "aligned", [0.0, 0.0, 0.0]
        forward = float(np.clip(0.8 * (m["forward_gap_m"] - 0.82), -0.06, 0.06))
        lateral = float(np.clip(1.2 * m["lateral_error_m"], -0.08, 0.08))
        e = m["heading_error_rad"]
        return "aligning", [
            math.cos(e) * forward - math.sin(e) * lateral,
            math.sin(e) * forward + math.cos(e) * lateral,
            float(np.clip(e, -0.15, 0.15)),
        ]
