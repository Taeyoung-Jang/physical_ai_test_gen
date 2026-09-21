"""Bounded GT-box feedback supervisor for a near-box push/retract unit probe."""

from dataclasses import dataclass

import numpy as np


@dataclass
class ContactControl:
    phase: str = "settle"
    retract_at: float | None = None
    retract_base: float | None = None
    release_seconds: float = 0.0
    previous_force: float = 0.0
    previous_contact: bool = False
    push_contact_seconds: float = 0.0

    def update(self, t, base, box, box_start, starts):
        if not np.isfinite([t, *base, *box, *box_start, self.previous_force]).all():
            raise ValueError("nonfinite supervisor observation")
        if t < 2:
            self.phase = "settle"
            return {}, 0.0
        if self.retract_at is None and t >= 5 and (box[0] - box_start[0] >= 0.12 or t >= 13):
            self.retract_at, self.retract_base = t, float(base[0])
        if self.retract_at is not None:
            elapsed = t - self.retract_at
            self.phase = "retract" if elapsed < 2 else "released_hold"
            alpha = min(elapsed / 2, 1.0)
            goals = {
                side: base + np.array([0.28 - 0.14 * alpha, sign * 0.20, -0.05 + 0.15 * alpha])
                for side, sign in (("left", 1), ("right", -1))
            }
            vx = float(np.clip((self.retract_base - 0.12 - base[0]) * 0.8, -0.12, 0.0))
            return goals, vx
        self.phase = "reach" if t < 5 else "push"
        alpha = float(np.clip((t - 2) / 3, 0, 1))
        # Reachable palm target tracks measured box face, not an imagined moved box.
        target_x = float(np.clip(box[0] - 0.4 + 0.02, base[0] + 0.24, base[0] + 0.30))
        goals = {
            side: (1 - alpha) * starts[side]
            + alpha
            * np.array(
                [
                    target_x,
                    box[1] + sign * 0.20,
                    base[2] - 0.05,
                ]
            )
            for side, sign in (("left", 1), ("right", -1))
        }
        # Slow on high measured per-contact force; hard 120 N stop is in the runner.
        vx = 0.22 if self.phase == "push" else 0.0
        if self.previous_force > 40:
            vx *= max(0.0, (80 - self.previous_force) / 40)
        return goals, vx

    def observe_contact(self, contact, force, dt):
        if not np.isfinite([force, dt]).all() or force < 0 or dt <= 0:
            raise ValueError("invalid contact observation")
        self.previous_contact, self.previous_force = bool(contact), float(force)
        if self.phase == "push" and contact:
            self.push_contact_seconds += dt
        self.release_seconds = (
            self.release_seconds + dt if self.phase == "released_hold" and not contact else 0.0
        )

    @property
    def released(self):
        return self.release_seconds >= 0.5
