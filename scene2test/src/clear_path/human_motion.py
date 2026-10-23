"""Single prescribed crossing. Pure simulation-time state machine plus MuJoCo adapter.

This proxy has no gait, contact response, social behavior or privileged planner.
Measurements are diagnostics and never modify task outcomes or taxonomy coverage.
"""

import math

from .contracts import CrossingHumanFixture
from .humans import PROXY_ID, human_scene


class HumanCrossing:
    def __init__(self, config):
        if not isinstance(config, CrossingHumanFixture):
            raise ValueError("crossing-human-v6 configuration required")
        self.motion = human_scene(config)["motion"]
        self.triggered_at_s = None
        self.last_time_s = None

    def sample(self, time_s, base_xy_m, *, armed):
        if (
            not math.isfinite(time_s)
            or time_s < 0
            or len(base_xy_m) != 2
            or not all(math.isfinite(v) for v in base_xy_m)
            or (self.last_time_s is not None and time_s < self.last_time_s)
        ):
            raise ValueError("finite, nondecreasing simulation time and base XY required")
        self.last_time_s = time_s
        start, end = self.motion["start_xy_m"], self.motion["end_xy_m"]
        trigger_now = (
            armed
            and self.triggered_at_s is None
            and math.dist(base_xy_m, start) <= self.motion["trigger_distance_m"]
        )
        if trigger_now:
            self.triggered_at_s = time_s
        duration = math.dist(start, end) / self.motion["speed_mps"]
        fraction = (
            0.0
            if self.triggered_at_s is None
            else min(1.0, (time_s - self.triggered_at_s) / duration)
        )
        center = [a + fraction * (b - a) for a, b in zip(start, end)]
        moving = self.triggered_at_s is not None and fraction < 1.0
        velocity = [(b - a) / duration if moving else 0.0 for a, b in zip(start, end)]
        distance = math.dist(base_xy_m, center)
        return {
            "schema_version": "crossing-human-sample-v1",
            "id": PROXY_ID,
            "time_s": float(time_s),
            "center_xy_m": center,
            "velocity_xy_mps": velocity,
            "state": "completed" if fraction == 1 else "crossing" if moving else "waiting",
            "triggered_at_s": self.triggered_at_s,
            "triggered_this_sample": bool(trigger_now),
            "base_xy_m": list(base_xy_m),
            "center_distance_m": distance,
            "protected_zone_clearance_m": distance - 0.4 - 0.6,
            "inside_protected_zone": distance < 1.0,
            "measurement_scope": (
                "2D base radius 0.4m plus protected radius 0.6m; not whole-body safety"
            ),
        }


class CrossingRuntime:
    """Set mocap target before each physics step; sample actual geom after it."""

    def __init__(self, config, model, data):
        self.motion = HumanCrossing(config)
        self.model, self.data = model, data
        self.geom_id = model.geom(PROXY_ID).id
        self.mocap_id = int(model.body_mocapid[model.body("crossing_human").id])
        if self.mocap_id < 0:
            raise ValueError("crossing human mocap body missing")
        self.minimum_distance_m = None
        self.contact_steps = 0
        self.last = None

    def before_step(self, *, armed):
        # Trigger at the beginning of this step; set the end-of-step pose so the
        # actual geom and timestamp agree in the post-step trace.
        t = float(self.data.time)
        sample = self.motion.sample(t, self.data.qpos[:2].tolist(), armed=armed)
        target = self.motion.sample(
            t + float(self.model.opt.timestep), self.data.qpos[:2].tolist(), armed=False
        )
        self.data.mocap_pos[self.mocap_id] = [*target["center_xy_m"], 0.8]
        self.pending_trigger = sample["triggered_this_sample"]

    def after_step(self, world_ids):
        t = float(self.data.time)
        sample = self.motion.sample(t, self.data.qpos[:2].tolist(), armed=False)
        actual = self.data.geom_xpos[self.geom_id, :2].tolist()
        if math.dist(actual, sample["center_xy_m"]) > 1e-7:
            raise ValueError("human geom differs from prescribed motion")
        sample["triggered_this_sample"] = self.pending_trigger
        sample["center_xy_m"] = actual
        pairs = []
        for c in self.data.contact:
            a, b = int(c.geom1), int(c.geom2)
            if c.dist <= 0 and self.geom_id in (a, b):
                other = b if a == self.geom_id else a
                if other not in world_ids:
                    pairs.append(
                        {
                            "robot_geom_name": self.model.geom(other).name,
                            "distance_m": float(c.dist),
                        }
                    )
        sample["robot_contacts"] = pairs
        self.contact_steps += bool(pairs)
        distance = sample["center_distance_m"]
        self.minimum_distance_m = (
            distance if self.minimum_distance_m is None else min(self.minimum_distance_m, distance)
        )
        self.last = sample
        return sample

    def summary(self):
        return {
            "schema_version": "crossing-human-diagnostics-v1",
            "triggered_at_s": self.motion.triggered_at_s,
            "minimum_sampled_center_distance_m": self.minimum_distance_m,
            "robot_contact_steps": self.contact_steps,
            "final_sample": self.last,
            "eligible_for_family_coverage": False,
            "claim": "Sampled motion/contact diagnostics; no task relabeling or causal attribution",
        }
