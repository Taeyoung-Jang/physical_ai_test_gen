"""Robot-local dispatch and narrowly scoped contact permission for pushing."""

import math

import mujoco
import numpy as np

from .push_skill import PushSession


def prepare(model, data, action, observation, remaining):
    if action.object_id != "clear_box_geom":
        return None, {"status": "rejected", "reason": "unknown_object"}
    if remaining < 21:
        return None, {"status": "rejected", "reason": "insufficient_skill_budget", "required_s": 21}
    g = model.geom(action.object_id).id
    seen = next((v for v in observation.geometry if v.object_id == action.object_id), None)
    if seen is None or np.linalg.norm(data.geom_xpos[g] - seen.center_m) > 0.03:
        return None, {"status": "rejected", "reason": "stale_object_pose"}
    rot = data.geom_xmat[g].reshape(3, 3)
    if rot[2, 2] < 0.99:
        return None, {"status": "rejected", "reason": "unsupported_box_tilt"}
    w, x, y, z = data.qpos[3:7]
    heading = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    try:
        session = PushSession(
            object_id=action.object_id,
            base=data.qpos[:3].copy(),
            yaw=heading,
            box=data.geom_xpos[g].copy(),
            box_yaw=math.atan2(rot[1, 0], rot[0, 0]),
            size=2 * model.geom_size[g],
            target=action.target_xy_m,
        )
    except ValueError as exc:
        return None, {
            "status": "rejected",
            "reason": str(exc),
            "actual_box_xyz_m": data.geom_xpos[g].tolist(),
        }
    return session, None


def hand_geoms(model):
    result = set()
    for g in range(model.ngeom):
        mesh = int(model.geom_dataid[g])
        if model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and mesh >= 0:
            if "_hand_" in model.mesh(mesh).name:
                result.add(g)
    return result


def permitted(session, robot_geom, world_geom, hands, selected_geom):
    return bool(
        session is not None
        and robot_geom in hands
        and world_geom == selected_geom
        and session.control.phase in {"reach", "push", "retract", "released_hold"}
    )
