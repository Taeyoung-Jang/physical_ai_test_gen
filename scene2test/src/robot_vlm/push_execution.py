"""Robot-local dispatch and narrowly scoped contact permission for pushing."""

import math

import mujoco
import numpy as np

from .push_alignment import MAX_SECONDS, Alignment, readiness
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
            "readiness": measure(model, data, action),
        }
    return session, None


def measure(model, data, action):
    g = model.geom(action.object_id).id
    rot = data.geom_xmat[g].reshape(3, 3)
    w, x, y, z = data.qpos[3:7]
    heading = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return readiness(
        data.qpos[:3],
        heading,
        data.geom_xpos[g],
        math.atan2(rot[1, 0], rot[0, 0]),
        2 * model.geom_size[g],
        action.target_xy_m,
    )


def align(model, data, action, observation, deadline, step, failed, record):
    """Use the runner's guarded physics step. No contact exemption while aligning."""
    start = float(data.time)
    initial = measure(model, data, action)
    summary = {"attempted": False, "initial": initial}
    if deadline - start < 21 + MAX_SECONDS:
        summary["status"] = "alignment_insufficient_budget"
        return None, {"status": "rejected", "reason": summary["status"]}, summary
    if not initial["correctable"]:
        summary["status"] = "alignment_out_of_range"
        return None, {"status": "rejected", "reason": summary["status"]}, summary
    summary["attempted"] = True
    heading = initial["measured"]["push_heading_rad"] - initial["measured"]["heading_error_rad"]
    control = Alignment(data.qpos[:3], heading)
    next_record = 0.0
    while True:
        elapsed = float(data.time) - start
        if failed():
            summary.update(
                status="alignment_safety_stop", elapsed_s=elapsed, travel_m=control.travel
            )
            record({"elapsed_s": elapsed, "status": "alignment_safety_stop"})
            return None, {"status": "rejected", "reason": "alignment_safety_stop"}, summary
        session, rejection = prepare(model, data, action, observation, deadline - float(data.time))
        state = measure(model, data, action)
        if rejection and rejection["reason"] not in {
            "near_aligned_approach_required",
            "approach_heading_required",
        }:
            status, command = rejection["reason"], [0.0, 0.0, 0.0]
        elif failed():
            status, command = "alignment_safety_stop", [0.0, 0.0, 0.0]
        else:
            yaw = state["measured"]["push_heading_rad"] - state["measured"]["heading_error_rad"]
            status, command = control.update(elapsed, data.qpos[:3], yaw, state)
        if elapsed >= next_record or status != "aligning":
            record(
                {
                    "elapsed_s": elapsed,
                    "status": status,
                    "readiness": state,
                    "command": command,
                    "travel_m": control.travel,
                }
            )
            next_record = elapsed + 0.05
        if status != "aligning":
            summary.update(status=status, final=state, elapsed_s=elapsed, travel_m=control.travel)
            if status == "aligned" and session is not None:
                return session, None, summary
            return None, {"status": "rejected", "reason": status, "readiness": state}, summary
        step(command)


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
