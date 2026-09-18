"""P2 unit probes: CUDA gait plus bounded position-IK arm targets.

Not a clear-path executor. Push probe starts near the box and pushes forward,
not into the side bay. Live state is advanced only by MuJoCo actuator dynamics.
"""

import json

import mujoco
import numpy as np

from clear_path.audit import initial_data
from clear_path.push_probe import ArmGaitController

from .push_skill import PushSession


def run_probe(
    model, groot_root, root, *, kind="push_contact", duration=18.0, initial_y=0.0, distance=0.08
):
    import imageio.v2 as imageio
    from PIL import Image, ImageDraw

    if kind != "push_contact" or not 16 <= duration <= 20 or abs(initial_y) > 0.03:
        raise ValueError("bounded probe kind/duration required")
    source = groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    controller = ArmGaitController(groot_root, model)
    if controller.execution_provider != "CUDAExecutionProvider":
        raise RuntimeError("probe requires CUDA gait")
    controller.data = initial_data(model, source)
    data = controller.data
    # Explicit initialization BEFORE first physics step; not robot navigation evidence.
    if kind == "push_contact":
        data.joint("floating_base_joint").qpos[0] = 3.2
    data.joint("floating_base_joint").qpos[1] = initial_y
    mujoco.mj_forward(model, data)
    box_start = data.body("clear_box").xpos.copy()
    skill = PushSession(
        object_id="clear_box",
        base=data.qpos[:3].copy(),
        yaw=0.0,
        box=box_start,
        box_yaw=0.0,
        size=[0.8, 1.1, 0.7],
        target=box_start[:2] + [distance, 0],
    )
    supervisor = skill.control
    initial = data.qpos.copy()
    box_geom = model.geom("clear_box_geom").id
    wall_geoms = {
        model.geom(name).id for name in __import__("clear_path.fixture", fromlist=["WALLS"]).WALLS
    }
    floor = model.geom("clear_floor").id
    world = wall_geoms | {floor, box_geom}
    robot = set(range(model.ngeom)) - world
    hand_geoms, foot_geoms = set(), set()
    for g in robot:
        body = model.body(int(model.geom_bodyid[g])).name
        if "ankle_roll" in body:
            foot_geoms.add(g)
        mesh = int(model.geom_dataid[g])
        if model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH and mesh >= 0:
            if "_hand_" in model.mesh(mesh).name:
                hand_geoms.add(g)
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 3.8, 120, -60
    frames, history, contacts = [], [], []
    phase, reason = "settle", "DURATION_REACHED"
    forbidden, fallen, valid = False, False, True
    hand_contact_steps, peak_force, max_error = 0, 0.0, 0.0
    goals = {}
    with (
        mujoco.Renderer(model, height=540, width=960) as renderer,
        imageio.get_writer(root / "rollout.mp4", fps=12, macro_block_size=2) as video,
        (root / "state_trajectory.jsonl").open("x") as states,
        (root / "contacts.jsonl").open("x") as contact_file,
    ):
        next_frame, next_log = 0.0, 0.0
        for step in range(int(duration / model.opt.timestep)):
            t = float(data.time)
            base = data.joint("floating_base_joint").qpos[:3]
            w, x, y, z = data.qpos[3:7]
            yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            goals, command = skill.command(
                t,
                base.copy(),
                yaw,
                data.body("clear_box").xpos.copy(),
                {side: data.site(f"{side}_push_site").xpos.copy() for side in ("left", "right")},
            )
            phase = supervisor.phase
            if goals and step % 10 == 0:
                controller.arm_targets(goals)
                max_error = max(max_error, controller.last_ik_error)
            controller.command[:] = command
            controller.step()
            mujoco.mj_forward(model, data)
            if any(
                data.warning[i].number
                for i in (
                    mujoco.mjtWarning.mjWARN_BADQPOS,
                    mujoco.mjtWarning.mjWARN_BADQVEL,
                    mujoco.mjtWarning.mjWARN_BADQACC,
                )
            ):
                valid, reason = False, "NUMERICAL_WARNING"
                break
            if not np.isfinite(data.qpos).all() or not np.isfinite(data.qvel).all():
                valid, reason = False, "NONFINITE_STATE"
                break
            # Never inject object forces, mocap, or state changes during stepping.
            if np.any(data.xfrc_applied) or np.any(data.qfrc_applied):
                valid, reason = False, "UNEXPECTED_EXTERNAL_FORCE"
                break
            step_contact = False
            step_force = 0.0
            for index, c in enumerate(data.contact):
                if c.dist > 0:
                    continue
                a, b = int(c.geom1), int(c.geom2)
                if not ((a in robot and b in world) or (b in robot and a in world)):
                    continue
                rg, wg = (a, b) if a in robot else (b, a)
                force = np.zeros(6)
                mujoco.mj_contactForce(model, data, index, force)
                normal = abs(float(force[0]))
                allowed = wg == floor and rg in foot_geoms
                if (
                    wg == box_geom
                    and rg in hand_geoms
                    and phase in {"reach", "push", "retract", "released_hold"}
                ):
                    allowed, step_contact = True, True
                    peak_force = max(peak_force, normal)
                    step_force = max(step_force, normal)
                    if normal > 120:
                        reason = "CONTACT_FORCE_LIMIT"
                if not allowed:
                    forbidden, reason = True, "FORBIDDEN_CONTACT"
                if wg != floor or not allowed:
                    row = {
                        "time_s": float(data.time),
                        "phase": phase,
                        "robot_geom": rg,
                        "robot_body": model.body(int(model.geom_bodyid[rg])).name,
                        "world_geom": model.geom(wg).name,
                        "normal_force_n": normal,
                        "allowed": allowed,
                    }
                    contacts.append(row)
                    contact_file.write(json.dumps(row) + "\n")
            skill.observe_contact(step_contact, step_force, model.opt.timestep)
            hand_contact_steps += int(step_contact)
            base = data.joint("floating_base_joint").qpos[:3]
            upright = float(data.xmat[model.body("pelvis").id].reshape(3, 3)[2, 2])
            if base[2] < 0.5 or upright < 0.7:
                fallen, reason = True, "FALLEN"
            if data.time >= next_log:
                row = {
                    "time_s": float(data.time),
                    "phase": phase,
                    "hand_contact": step_contact,
                    "hand_normal_force_n": step_force,
                    "release_seconds": supervisor.release_seconds,
                    "qpos": data.qpos.tolist(),
                    "qvel": data.qvel.tolist(),
                    "ctrl": data.ctrl.tolist(),
                    "base_xyz": base.tolist(),
                    "box_xyz": data.body("clear_box").xpos.tolist(),
                    "upper_target": controller.upper_target.tolist(),
                    "command": controller.command.tolist(),
                    "palm_targets": {s: v.tolist() for s, v in goals.items()},
                    "palms": {
                        s: data.site(f"{s}_push_site").xpos.tolist() for s in ("left", "right")
                    },
                }
                states.write(json.dumps(row, allow_nan=False) + "\n")
                history.append(row)
                next_log += 0.05
            if data.time >= next_frame:
                camera.lookat[:] = [base[0] + 0.4, base[1], 0.65]
                renderer.update_scene(data, camera=camera)
                frame = Image.fromarray(renderer.render())
                draw = ImageDraw.Draw(frame)
                draw.rectangle((0, 0, 960, 32), fill="#0f172a")
                draw.text(
                    (12, 10),
                    f"REAL PHYSICS PROBE: {kind} | t={data.time:.2f}s | {phase} | CUDA gait",
                    fill="white",
                )
                arr = np.asarray(frame).copy()
                video.append_data(arr)
                frames.append(arr)
                next_frame += 1 / 12
            if forbidden or fallen or reason == "CONTACT_FORCE_LIMIT":
                break
    if frames:
        imageio.mimsave(root / "rollout.gif", frames, duration=1000 / 12, loop=0)
        imageio.imwrite(root / "final_frame.png", frames[-1])
    displacement = data.body("clear_box").xpos - box_start
    final_error = max(
        (float(np.linalg.norm(data.site(f"{s}_push_site").xpos - v)) for s, v in goals.items()),
        default=None,
    )
    legacy_probe_success = bool(
        valid
        and not forbidden
        and not fallen
        and reason == "DURATION_REACHED"
        and hand_contact_steps > 0
        and displacement[0] > 0.08
        and supervisor.released
    )
    measured = skill.result(data.body("clear_box").xpos.tolist(), valid=valid, reason=reason)
    return {
        "schema_version": "clear-path-probe-result-v1",
        "controller_condition": "near-contact-push-v1",
        "kind": kind,
        "released": supervisor.released,
        "release_seconds": supervisor.release_seconds,
        "push_contact_seconds": supervisor.push_contact_seconds,
        "retract_started_at_s": supervisor.retract_at,
        "execution_provider": controller.execution_provider,
        "valid_execution": valid,
        "probe_success": measured["success"],
        "legacy_8cm_probe_success": legacy_probe_success,
        "skill_result": measured,
        "clear_path_success": None,
        "termination_reason": reason,
        "duration_s": float(data.time),
        "fallen": fallen,
        "forbidden_contact": forbidden,
        "hand_contact_steps": hand_contact_steps,
        "peak_hand_normal_force_n": peak_force,
        "box_displacement_xyz_m": displacement.tolist(),
        "final_palm_error_m": final_error,
        "maximum_recorded_palm_error_m": max_error,
        "initial_qpos": initial.tolist(),
        "final_qpos": data.qpos.tolist(),
        "frames": len(frames),
        "self_collision_classification": "not_implemented",
        "initial_condition": "near-box unit probe" if kind == "push_contact" else "original spawn",
        "limitations": "No approach, side-bay clearing or goal traversal validated",
    }
