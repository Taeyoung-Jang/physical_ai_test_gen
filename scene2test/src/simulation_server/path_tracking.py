"""Versioned, opt-in straight-path command supervisor; no policy weight changes."""

import math

import numpy as np


def path_errors(position, quaternion, origin, heading):
    w, x, y, z = quaternion
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    error = math.atan2(math.sin(yaw - heading), math.cos(yaw - heading))
    offset = np.asarray(position)[:2] - np.asarray(origin)[:2]
    cross_track = -math.sin(heading) * offset[0] + math.cos(heading) * offset[1]
    return float(cross_track), error


def supervised_command(command, cross_track, heading_error):
    result = np.array(command, dtype=np.float32, copy=True)
    result[2] = np.clip(-1.5 * heading_error - 0.8 * cross_track, -0.5, 0.5)
    return result


def contact_slip_speeds(model, data, support_geom_ids=None):
    """Tangential relative velocity at ankle/plane contact points, in m/s."""
    import mujoco

    speeds = []
    for contact in data.contact[: data.ncon]:
        if contact.dist > 0:
            continue
        geoms = (int(contact.geom1), int(contact.geom2))
        if not any(
            (g in support_geom_ids)
            if support_geom_ids is not None
            else (model.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE)
            for g in geoms
        ):
            continue
        bodies = [int(model.geom_bodyid[g]) for g in geoms]
        if not any(
            "ankle_roll" in (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, b) or "")
            for b in bodies
        ):
            continue
        velocities = []
        for body in bodies:
            jac = np.zeros((3, model.nv))
            mujoco.mj_jac(model, data, jac, None, contact.pos, body)
            velocities.append(jac @ data.qvel)
        relative = velocities[0] - velocities[1]
        normal = np.asarray(contact.frame).reshape(3, 3)[0]
        tangent = relative - np.dot(relative, normal) * normal
        speeds.append(float(np.linalg.norm(tangent)))
    return speeds
