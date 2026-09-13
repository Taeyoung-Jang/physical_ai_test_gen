"""Navigation-only terrain measurements; legacy stand/locomotion worker is unchanged."""

import math

from procedural_world.terrain import ground_height

from .path_tracking import contact_slip_speeds


class TerrainMetrics:
    def __init__(self, spec, model):
        import mujoco

        self.spec, self.model = spec, model
        self.support_ids = {model.geom("world_" + s.id).id for s in spec.surfaces}
        self.foot_ids = {
            g
            for g in range(model.ngeom)
            if "ankle_roll"
            in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, int(model.geom_bodyid[g])) or "")
        }
        self.robot_ids = {g for g in range(model.ngeom) if model.geom_bodyid[g] != 0}
        self.minimum_clearance = math.inf
        self.samples, self.slip_square_sum, self.max_slip = 0, 0.0, 0.0

    def update(self, data):
        clearance = float(data.qpos[2]) - ground_height(self.spec, data.qpos[:2])
        self.minimum_clearance = min(self.minimum_clearance, clearance)
        for speed in contact_slip_speeds(self.model, data, self.support_ids):
            self.samples += 1
            self.slip_square_sum += speed * speed
            self.max_slip = max(self.max_slip, speed)
        return clearance

    def nonfoot_collision(self, contact):
        geoms = (int(contact.geom1), int(contact.geom2))
        return any(
            a in self.support_ids and b in self.robot_ids - self.foot_ids
            for a, b in (geoms, geoms[::-1])
        )

    def result(self):
        return {
            "minimum_base_ground_clearance_m": self.minimum_clearance,
            "foot_contact_sample_count": self.samples,
            "foot_slip_measurement_valid": self.samples > 0,
            "foot_contact_slip_rms_mps": math.sqrt(self.slip_square_sum / self.samples)
            if self.samples
            else None,
            "maximum_foot_contact_slip_mps": self.max_slip if self.samples else None,
        }
