"""P2 unit probes: CUDA gait plus bounded position-IK arm targets.

Not a clear-path executor. Push probe starts near the box and pushes forward,
not into the side bay. Live state is advanced only by MuJoCo actuator dynamics.
"""

import json

import mujoco
import numpy as np

from simulation_server.groot_locomotion import G1OnnxController

from .audit import initial_data, joint_table


class ArmGaitController(G1OnnxController):
    def __init__(self, groot_root, model):
        super().__init__(groot_root, "walk", np.zeros(3), model=model)
        self.rows = joint_table(model)
        self.upper = self.rows[self.config["num_actions"] :]
        self.upper_target = np.zeros(len(self.upper))
        self.scratch = mujoco.MjData(model)
        self.last_ik_error = 0.0

    def arm_targets(self, targets):
        """IK modifies scratch qpos only; rate-limited targets drive real actuators."""
        if set(targets) != {"left", "right"}:
            raise ValueError("both palm targets required")
        for target in targets.values():
            value = np.asarray(target)
            if value.shape != (3,) or not np.isfinite(value).all():
                raise ValueError("finite 3D palm target required")
        self.scratch.qpos[:] = self.data.qpos
        for side, target in targets.items():
            rows = [r for r in self.upper if r["joint"].startswith(side + "_")]
            qi, vi = [r["qpos_adr"] for r in rows], [r["dof_adr"] for r in rows]
            sid = self.model.site(f"{side}_push_site").id
            for _ in range(12):
                mujoco.mj_forward(self.model, self.scratch)
                error = target - self.scratch.site_xpos[sid]
                if np.linalg.norm(error) < 0.008:
                    break
                jac = np.zeros((3, self.model.nv))
                mujoco.mj_jacSite(self.model, self.scratch, jac, None, sid)
                j = jac[:, vi]
                delta = j.T @ np.linalg.solve(j @ j.T + 0.003 * np.eye(3), error)
                q = self.scratch.qpos[qi] + np.clip(delta, -0.08, 0.08)
                lo, hi = np.asarray([r["range_rad"] for r in rows]).T
                self.scratch.qpos[qi] = np.clip(q, lo + 0.02, hi - 0.02)
        desired = self.scratch.qpos[[r["qpos_adr"] for r in self.upper]]
        # Called at 20 Hz; maximum target angular speed 0.8 rad/s.
        self.upper_target += np.clip(desired - self.upper_target, -0.04, 0.04)
        self.last_ik_error = max(
            float(np.linalg.norm(self.data.site(f"{side}_push_site").xpos - target))
            for side, target in targets.items()
        )

    def step(self):
        cfg, data, model = self.config, self.data, self.model
        n = cfg["num_actions"]
        qi, vi = [r["qpos_adr"] for r in self.rows], [r["dof_adr"] for r in self.rows]
        data.ctrl[:n] = (self.target - data.qpos[qi[:n]]) * cfg["kps"] - data.qvel[vi[:n]] * cfg[
            "kds"
        ]
        data.ctrl[n:] = (
            (self.upper_target - data.qpos[qi[n:]]) * 80
            - data.qvel[vi[n:]] * 4
            + data.qfrc_bias[vi[n:]]
        )
        for i, row in enumerate(self.rows):
            joint = model.joint(row["joint"]).id
            if model.jnt_actfrclimited[joint]:
                data.ctrl[i] = np.clip(data.ctrl[i], *model.jnt_actfrcrange[joint])
        mujoco.mj_step(model, data)
        self.counter += 1
        if self.counter % cfg["control_decimation"] == 0:
            self.history.append(self._observation())
            inputs = np.concatenate(self.history)[None, :].astype(np.float32)
            self.action = self.session.run(None, {self.input_name: inputs})[0][0]
            if not np.isfinite(self.action).all():
                raise ValueError("nonfinite policy output")
            self.target = self.action * cfg["action_scale"] + cfg["default_angles"]


def run_probe(model, groot_root, root, *, kind="arm_reach", duration=8.0):
    import imageio.v2 as imageio
    from PIL import Image, ImageDraw

    if kind not in {"arm_reach", "push_contact"} or not 4 <= duration <= 20:
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
    mujoco.mj_forward(model, data)
    box_start = data.body("clear_box").xpos.copy()
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
    starts = None
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
            if t >= 2 and starts is None:
                starts = {
                    side: data.site(f"{side}_push_site").xpos.copy() for side in ("left", "right")
                }
            if t >= 2:
                phase = "reach" if t < 5 else "push" if kind == "push_contact" and t < 9 else "hold"
                alpha = np.clip((t - 2) / 3, 0, 1)
                for side, sign in (("left", 1), ("right", -1)):
                    target = (
                        base + [0.26, sign * 0.20, -0.05]
                        if kind == "push_contact"
                        else starts[side] + [0.12, 0, -0.12]
                    )
                    goals[side] = starts[side] * (1 - alpha) + target * alpha
                if step % 10 == 0:
                    controller.arm_targets(goals)
                    max_error = max(max_error, controller.last_ik_error)
                controller.command[:] = [
                    0.18 if phase == "push" else 0,
                    np.clip(-base[1] * 0.5, -0.06, 0.06),
                    0,
                ]
            # Explicit base-hold controller condition, not the unmodified gait baseline.
            root_pose = data.joint("floating_base_joint").qpos
            w, x, y, z = root_pose[3:7]
            yaw = np.arctan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            if phase != "push":
                controller.command[0] = np.clip((initial[0] - root_pose[0]) * 0.8, -0.12, 0.12)
            controller.command[1] = np.clip((initial[1] - root_pose[1]) * 0.8, -0.08, 0.08)
            controller.command[2] = np.clip(-yaw, -0.3, 0.3)
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
                if wg == box_geom and rg in hand_geoms and phase in {"reach", "push", "hold"}:
                    allowed, step_contact = True, True
                    peak_force = max(peak_force, normal)
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
            hand_contact_steps += int(step_contact)
            base = data.joint("floating_base_joint").qpos[:3]
            upright = float(data.xmat[model.body("pelvis").id].reshape(3, 3)[2, 2])
            if base[2] < 0.5 or upright < 0.7:
                fallen, reason = True, "FALLEN"
            if data.time >= next_log:
                row = {
                    "time_s": float(data.time),
                    "phase": phase,
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
    reached = final_error is not None and final_error < 0.08
    success = bool(
        valid
        and not forbidden
        and not fallen
        and reason == "DURATION_REACHED"
        and (reached if kind == "arm_reach" else hand_contact_steps > 0 and displacement[0] > 0.08)
    )
    return {
        "schema_version": "clear-path-probe-result-v1",
        "controller_condition": "gait_arm_ik_base_hold_v4",
        "kind": kind,
        "execution_provider": controller.execution_provider,
        "valid_execution": valid,
        "probe_success": success,
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
        "limitations": "No approach, side-bay clearing, release or goal traversal validated",
    }
