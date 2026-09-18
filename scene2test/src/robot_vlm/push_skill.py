"""Experimental near-contact push skill; no route, object teleport or task strategy.

The caller selects the object and target. This controller only accepts an already
aligned approach to a supported box. It is not a grasp or jump policy.
"""

import math

import numpy as np

from clear_path.contact_control import ContactControl

VERSION = "near-contact-push-v1"


def angle_error(a, b):
    return math.atan2(math.sin(a - b), math.cos(a - b))


def preflight(base, yaw, box, box_yaw, size, target):
    """Return a reason, not a fabricated successful execution, for unsupported input."""
    if (
        np.shape(base) != (3,)
        or np.shape(box) != (3,)
        or np.shape(size) != (3,)
        or np.shape(target) != (2,)
    ):
        return "invalid_shape"
    if not np.isfinite([*base, yaw, *box, box_yaw, *size, *target]).all():
        return "nonfinite_input"
    if not np.allclose(size, [0.8, 1.1, 0.7], atol=0.001):
        return "unsupported_box_geometry"
    delta = np.asarray(target) - np.asarray(box)[:2]
    distance = float(np.linalg.norm(delta))
    if not 0.075 <= distance <= 0.20:
        return "unsupported_push_distance"
    heading = math.atan2(delta[1], delta[0])
    if abs(angle_error(yaw, heading)) > 0.12:
        return "approach_heading_required"
    if abs(angle_error(box_yaw, heading)) > 0.12:
        return "unsupported_box_face"
    forward = np.array([math.cos(heading), math.sin(heading)])
    lateral = np.array([-forward[1], forward[0]])
    gap = np.asarray(box)[:2] - np.asarray(base)[:2]
    if not 0.72 <= gap @ forward <= 0.90 or abs(gap @ lateral) > 0.06:
        return "near_aligned_approach_required"
    if not 0.65 <= base[2] <= 0.85 or not 0.30 <= box[2] <= 0.40:
        return "unsupported_height"
    return None


class PushSession:
    """Reusable, bounded 18-second skill with measured displacement/release feedback."""

    def __init__(self, *, object_id, base, yaw, box, box_yaw, size, target):
        reason = preflight(base, yaw, box, box_yaw, size, target)
        if reason:
            raise ValueError(reason)
        self.object_id = object_id
        self.target = np.asarray(target).copy()
        self.box_start = np.asarray(box).copy()
        self.base_start = np.asarray(base).copy()
        delta = self.target - self.box_start[:2]
        self.distance = float(np.linalg.norm(delta))
        self.heading = math.atan2(delta[1], delta[0])
        c, s = math.cos(self.heading), math.sin(self.heading)
        self.rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        self.control = ContactControl()
        self.starts = None
        self.peak_force = 0.0
        self.elapsed = 0.0

    def command(self, elapsed, base, yaw, box, palms):
        if not np.isfinite([elapsed, *base, yaw, *box]).all() or elapsed < self.elapsed:
            raise ValueError("invalid skill state/time")
        self.elapsed = elapsed
        local_base = self.rotation.T @ base
        local_box = self.rotation.T @ box
        local_start = self.rotation.T @ self.box_start
        if elapsed >= 2 and self.starts is None:
            self.starts = {side: self.rotation.T @ p for side, p in palms.items()}
        # ContactControl retracts at +0.12; translate its reference to the requested distance.
        reference = local_start.copy()
        reference[0] += self.distance - 0.12
        goals, vx = self.control.update(elapsed, local_base, local_box, reference, self.starts)
        anchor = self.rotation.T @ self.base_start
        if self.control.phase in {"settle", "reach"}:
            vx = float(np.clip((anchor[0] - local_base[0]) * 0.8, -0.12, 0.12))
        vy = float(np.clip((anchor[1] - local_base[1]) * 0.8, -0.08, 0.08))
        error = angle_error(self.heading, yaw)
        command = [
            math.cos(error) * vx - math.sin(error) * vy,
            math.sin(error) * vx + math.cos(error) * vy,
            float(np.clip(error, -0.3, 0.3)),
        ]
        return {side: self.rotation @ p for side, p in goals.items()}, command

    def observe_contact(self, contact, force, dt):
        self.control.observe_contact(contact, force, dt)
        self.peak_force = max(self.peak_force, force)

    def result(self, box, *, valid=True, reason="DURATION_REACHED"):
        displacement = self.rotation.T @ (np.asarray(box) - self.box_start)
        error = float(np.linalg.norm(np.asarray(box)[:2] - self.target))
        success = bool(
            valid
            and reason == "DURATION_REACHED"
            and self.elapsed >= 17.9
            and error <= 0.02
            and self.control.push_contact_seconds > 0
            and self.control.released
            and self.peak_force <= 120
        )
        return {
            "skill_version": VERSION,
            "object_id": self.object_id,
            "success": success,
            "status": "succeeded" if success else "failed",
            "reason": reason,
            "valid_execution": valid,
            "target_xy_m": self.target.tolist(),
            "actual_box_xyz_m": list(box),
            "target_error_m": error,
            "displacement_push_frame_m": displacement.tolist(),
            "released": self.control.released,
            "contact_seconds": self.control.push_contact_seconds,
            "peak_contact_force_n": self.peak_force,
            "claim": "near-contact push only; no autonomous approach or path clearing",
        }
