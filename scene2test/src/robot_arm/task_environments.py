"""Initialization-only environments for Object butter and Goal drawer probes.

No edits to the policy, native success predicate, or existing experiment adapters.
"""

import json
import math
import os
import sys
import xml.etree.ElementTree as ET

from robot_arm import placement

TASKS = {
    "object": ("libero_object", "pick_up_the_butter_and_place_it_in_the_basket"),
    "goal": ("libero_goal", "open_the_middle_drawer_of_the_cabinet"),
}
PREFIX = "s2t_task_obstacle"
JOINT = "wooden_cabinet_1_middle_level"


def obstacle(task, p):
    if task == "object":
        x, y, yaw, surface = p["box_x"], p["box_y"], p["box_yaw"], 0.0
    else:
        t = p["cabinet_yaw_delta"]
        # Lateral / forward in the cabinet's nominal outward frame (+world Y).
        x = p["cabinet_x"] + math.cos(t) * p["box_lateral"] - math.sin(t) * p["box_forward"]
        y = p["cabinet_y"] + math.sin(t) * p["box_lateral"] + math.cos(t) * p["box_forward"]
        yaw, surface = t + p["box_yaw"], 0.9
    return {
        "xyz": [x, y, surface + p["box_height"] / 2],
        "size": [p["box_width"] / 2, p["box_depth"] / 2, p["box_height"] / 2],
        "yaw": yaw,
        "surface": surface,
    }


def inject(xml, task, p):
    root = ET.fromstring(xml)
    world = root.find("worldbody")
    if world is None or root.find(f".//*[@name='{PREFIX}']") is not None:
        raise ValueError("missing world or duplicate obstacle")
    box = obstacle(task, p)
    body = ET.SubElement(
        world,
        "body",
        name=PREFIX,
        pos=" ".join(map(str, box["xyz"])),
        quat=f"{math.cos(box['yaw'] / 2)} 0 0 {math.sin(box['yaw'] / 2)}",
    )
    ET.SubElement(
        body,
        "geom",
        name=PREFIX + "_geom",
        type="box",
        size=" ".join(map(str, box["size"])),
        contype="1",
        conaffinity="1",
        group="0",
        rgba="0.95 0.25 0.08 1",
        friction="1 0.005 0.0001",
    )
    if task == "object":
        target = root.find(".//body[@name='butter_1_main']")
        if target is None or target.find("inertial") is not None:
            raise ValueError("expected density-defined native butter")
        for geom in target.findall("geom"):
            if geom.get("mass") is not None:
                raise ValueError("unexpected explicit geom mass")
            geom.set("density", str(float(geom.get("density", "1000")) * p["butter_mass_scale"]))
            friction = geom.get("friction", "1 0.005 0.0001").split()
            friction[0] = str(p["butter_friction"])
            geom.set("friction", " ".join(friction))
    else:
        joint = root.find(f".//joint[@name='{JOINT}']")
        if joint is None or joint.get("range") != "-0.16 0.01":
            raise ValueError("unexpected native drawer range")
        joint.set("damping", str(50 * p["drawer_damping_scale"]))
        joint.set("frictionloss", str(p["drawer_frictionloss_n"]))
    return ET.tostring(root, encoding="unicode")


def snapshot(control, task):
    raw, sim = control.env, control.sim
    names = ("butter_1", "basket_1") if task == "object" else ("wooden_cabinet_1",)
    objects = {**raw.objects_dict, **raw.fixtures_dict}
    result = {
        n: {
            "xyz_m": sim.data.body_xpos[sim.model.body_name2id(objects[n].root_body)].tolist(),
            "quat_wxyz": sim.data.body_xquat[sim.model.body_name2id(objects[n].root_body)].tolist(),
        }
        for n in names
    }
    if task == "goal":
        result["drawer_qpos_m"] = float(sim.data.get_joint_qpos(JOINT))
    return result


def groups(control):
    raw, sim = control.env, control.sim
    objects = {**raw.objects_dict, **raw.fixtures_dict}
    result = {n: {sim.model.geom_name2id(g) for g in o.contact_geoms} for n, o in objects.items()}
    result[PREFIX] = {sim.model.geom_name2id(PREFIX + "_geom")}
    return result


def apply(control, task, p):
    import mujoco
    import numpy as np

    raw, sim = control.env, control.sim
    before = snapshot(control, task)
    requested = {}
    if task == "object":
        for short in ("butter", "basket"):
            name = short + "_1"
            joint = raw.objects_dict[name].joints[-1]
            q = sim.data.get_joint_qpos(joint).copy()
            q[:2] = [p[short + "_x"], p[short + "_y"]]
            yaw = p[short + "_yaw"]
            q[3:] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
            sim.data.set_joint_qpos(joint, q)
            requested[name] = q[:2].tolist()
    else:
        name = "wooden_cabinet_1"
        bid = sim.model.body_name2id(raw.fixtures_dict[name].root_body)
        sim.model.body_pos[bid, :2] = [p["cabinet_x"], p["cabinet_y"]]
        yaw = math.pi + p["cabinet_yaw_delta"]
        sim.model.body_quat[bid] = [math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]
        sim.data.set_joint_qpos(JOINT, 0.0)
        # Move one background plate away from the drawer corridor, identically in both arms.
        joint = raw.objects_dict["plate_1"].joints[-1]
        q = sim.data.get_joint_qpos(joint).copy()
        q[:2] = [0.25, 0.08]
        sim.data.set_joint_qpos(joint, q)
        requested = {name: [p["cabinet_x"], p["cabinet_y"]], "plate_1": [0.25, 0.08]}
    sim.forward()
    entities = groups(control)
    selected_names = set(requested) | {PREFIX}
    owner = {g: n for n, ids in entities.items() for g in ids}
    selected = set().union(*(entities[n] for n in selected_names))
    collision = [
        g
        for g in range(sim.model.ngeom)
        if sim.model.geom_contype[g] or sim.model.geom_conaffinity[g]
    ]
    problems, contacts, seen = [], [], set()
    for a in selected:
        for b in collision:
            pair = tuple(sorted((a, b)))
            if a == b or pair in seen or owner.get(a) == owner.get(b):
                continue
            seen.add(pair)
            other = sim.model.geom_id2name(b) or ""
            if other in {"floor", "table_collision"} or other.startswith("table_visual"):
                continue
            if np.linalg.norm(sim.data.geom_xpos[a] - sim.data.geom_xpos[b]) > (
                sim.model.geom_rbound[a] + sim.model.geom_rbound[b] + 1e-6
            ):
                continue
            distance = float(
                mujoco.mj_geomDistance(sim.model._model, sim.data._data, a, b, 1.0, None)
            )
            if distance < -1e-6:
                contacts.append(
                    {"geoms": [sim.model.geom_id2name(a), other], "distance_m": distance}
                )
    if contacts:
        problems.append("initial_penetration")
    if control.check_success():
        problems.append("already_successful_initial_state")
    after = snapshot(control, task)
    for name in set(requested) - {"plate_1"}:
        if not np.allclose(after[name]["xyz_m"][:2], requested[name], atol=1e-7, rtol=0):
            problems.append("pose_mismatch:" + name)
    # Exact rotated box AABBs avoid rejecting tall, narrow objects via a 3D sphere.
    limits = [0.45, 0.45] if task == "object" else [0.5, 0.6]
    for g in selected:
        if int(sim.model.geom_type[g]) == int(mujoco.mjtGeom.mjGEOM_BOX):
            extent = np.abs(sim.data.geom_xmat[g].reshape(3, 3)) @ sim.model.geom_size[g]
        else:
            extent = np.repeat(sim.model.geom_rbound[g], 3)
        if np.any(np.abs(sim.data.geom_xpos[g][:2]) + extent[:2] > limits):
            problems.append("outside_workspace")
    boxid = sim.model.geom_name2id(PREFIX + "_geom")
    compiled = {
        "xyz_m": sim.data.geom_xpos[boxid].tolist(),
        "rotation": sim.data.geom_xmat[boxid].tolist(),
        "half_size_m": sim.model.geom_size[boxid].tolist(),
    }
    physical = {}
    if task == "object":
        bid = sim.model.body_name2id(raw.objects_dict["butter_1"].root_body)
        physical = {
            "butter_mass_kg": float(sim.model.body_mass[bid]),
            "butter_inertia": sim.model.body_inertia[bid].tolist(),
            "butter_friction": [sim.model.geom_friction[g].tolist() for g in entities["butter_1"]],
        }
    else:
        jid = sim.model.joint_name2id(JOINT)
        dof = int(sim.model.jnt_dofadr[jid])
        physical = {
            "drawer_damping": float(sim.model.dof_damping[dof]),
            "drawer_frictionloss_n": float(sim.model.dof_frictionloss[dof]),
            "drawer_range_m": sim.model.jnt_range[jid].tolist(),
        }
    return {
        "valid": not problems,
        "problems": sorted(set(problems)),
        "penetrations": contacts,
        "before": before,
        "after": after,
        "requested": requested,
        "compiled_obstacle": compiled,
        "physical_properties": physical,
        "coordinate_frame": "world XY metres; Goal tabletop z=0.9; Object floor z=0",
        "claim": "Initial geometry only; not reachability or successful policy proof",
    }


class Recorder:
    def __init__(self, control, task, directory):
        self.control, self.task = control, task
        self.sim = control.sim
        self.stream = (directory / "physics.jsonl").open("x")
        self.original_step = control.sim.step
        self.entities = groups(control)
        self.robot = {
            g
            for g in range(control.sim.model.ngeom)
            if (control.sim.model.geom_id2name(g) or "").startswith(("robot0_", "gripper0_"))
        }
        self.sample()

        def step(*args, **kwargs):
            result = self.original_step(*args, **kwargs)
            self.sample()
            return result

        control.sim.step = step

    def sample(self):
        import mujoco
        import numpy as np

        sim = self.control.sim
        contacts = []
        target = self.entities["butter_1" if self.task == "object" else "wooden_cabinet_1"]
        box = self.entities[PREFIX]
        for i in range(sim.data.ncon):
            c = sim.data.contact[i]
            a, b = int(c.geom1), int(c.geom2)
            pair = {a, b}
            kind = None
            if pair & box:
                kind = (
                    "robot_obstacle"
                    if pair & self.robot
                    else "target_obstacle"
                    if pair & target
                    else "other_obstacle"
                )
            elif pair & target and pair & self.robot:
                kind = "robot_target"
            if kind:
                force = np.zeros(6)
                mujoco.mj_contactForce(sim.model._model, sim.data._data, i, force)
                contacts.append(
                    {
                        "kind": kind,
                        "distance_m": float(c.dist),
                        "force_n": float(np.linalg.norm(force[:3])),
                    }
                )
        row = {
            "time_s": float(sim.data.time),
            "dt_s": float(sim.model.opt.timestep),
            "state": snapshot(self.control, self.task),
            "contacts": contacts,
        }
        self.stream.write(json.dumps(row, allow_nan=False) + "\n")

    def close(self):
        self.sim.step = self.original_step
        self.stream.close()


def run_episode(design, candidate, directory):
    task, robot = design["task"], design["robot"]
    p = candidate["parameters"]
    os.environ["LIBERO_CONFIG_PATH"] = robot["libero_config_path"]
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, robot["upstream_root"])
    import gymnasium as gym
    from gr00t.eval import rollout_policy as rollout
    from gr00t.eval.sim.LIBERO.libero_env import LiberoEnv, register_libero_envs

    recorders = []

    class TaskEnv(LiberoEnv):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._env.env.set_xml_processor(lambda xml: inject(xml, task, p))
            self.resets = 0

        def reset(self, seed=None, options=None):
            self.resets += 1
            if self.resets > 1:
                self.terminal_reset = True
                return self.last, {"success": self._env.check_success()}
            self._env.seed(design["background_seed"])
            self._env.env.reset()  # One reset; never use the upstream unbounded retry loop.
            audit = apply(self._env, task, p)
            placement.save(directory / "initial_state.json", audit)
            (directory / "scene.xml").write_text(self._env.sim.model.get_xml())
            if not audit["valid"]:
                raise ValueError("invalid initial geometry")
            placement.save(
                directory / "initial_sim_state.json", {"state": self._env.get_sim_state().tolist()}
            )
            if self._env.env.control_freq != 20:
                raise ValueError("20Hz measurement contract required")
            recorders.append(Recorder(self._env, task, directory))
            self._env.env._update_observables(force=True)
            self.last = self._process_observation(
                self._env.env._get_observations(force_update=True)
            )
            self.terminal_reset = False
            return self.last, {"success": self._env.check_success()}

        def step(self, action):
            if self.terminal_reset:
                raise RuntimeError("unexpected extra rollout")
            result = super().step(action)
            self.last = result[0]
            with (directory / "trace.jsonl").open("a") as stream:
                stream.write(
                    json.dumps(
                        {"state": snapshot(self._env, task), "success": bool(result[4]["success"])}
                    )
                    + "\n"
                )
            return result

    def factory(name):
        def make():
            register_libero_envs()
            return TaskEnv(**gym.spec(name).kwargs)

        return make

    rollout.get_libero_env_fn = factory
    try:
        result = rollout.run_gr00t_sim_policy(
            env_name=robot["env_name"],
            n_episodes=1,
            max_episode_steps=300,
            model_path=robot["model_path"],
            n_envs=1,
            n_action_steps=8,
            video_dir=str(directory / "videos"),
            seed=candidate["scene_seed"],
        )
        lengths = result[2].get("episode_lengths", [])
        if len(result[1]) != 1 or len(lengths) != 1 or not 1 <= lengths[0] <= 300:
            raise RuntimeError("missing/filtered/out-of-budget outcome")
        return {
            "status": "VALID",
            "task_outcome": "PASS" if result[1][0] else "FAIL",
            "steps": [int(lengths[0])],
            "scene_seed": candidate["scene_seed"],
            "success_rule": "unmodified LIBERO check_success",
        }
    finally:
        for recorder in recorders:
            recorder.close()


def measure(directory, receipt, task):
    path = directory / "physics.jsonl"
    if receipt["status"] != "VALID" or not path.exists():
        return {"status": "UNKNOWN", "pattern": None, "cause": "UNCONFIRMED"}
    rows = [json.loads(s) for s in path.read_text().splitlines()]
    if len(rows) < 2:
        return {"status": "UNKNOWN", "pattern": None, "cause": "UNCONFIRMED"}
    dt = rows[0]["dt_s"]
    elapsed = rows[-1]["time_s"] - rows[0]["time_s"]
    if (
        any(abs(b["time_s"] - a["time_s"] - dt) > 1e-6 for a, b in zip(rows, rows[1:]))
        or abs(elapsed - receipt["steps"][0] / 20) > dt * 2
    ):
        return {
            "status": "UNKNOWN",
            "pattern": None,
            "reason": "incomplete_physics",
            "cause": "UNCONFIRMED",
        }
    result = {
        "status": "COMPLETE",
        "samples": len(rows),
        "elapsed_s": elapsed,
        "cause": "UNCONFIRMED",
        "contact_seconds": {},
    }
    for kind in ("robot_obstacle", "target_obstacle", "robot_target"):
        result["contact_seconds"][kind] = dt * sum(
            any(
                c["kind"] == kind and (c["distance_m"] <= 1e-6 or c["force_n"] > 0)
                for c in row["contacts"]
            )
            for row in rows[1:]
        )
    if task == "goal":
        initial = rows[0]["state"]["drawer_qpos_m"]
        final = rows[-1]["state"]["drawer_qpos_m"]
        travel = max(initial - r["state"]["drawer_qpos_m"] for r in rows)
        result.update(
            initial_drawer_qpos_m=initial, final_drawer_qpos_m=final, max_outward_travel_m=travel
        )
        result["pattern"] = (
            "little_drawer_motion" if travel < 0.01 else "drawer_moved_native_task_incomplete"
        )
    else:
        selected = [r for r in rows if r["time_s"] - rows[0]["time_s"] >= 1]
        if not selected:
            result.update(pattern="UNKNOWN", motion_status="UNKNOWN")
            return result
        anchor = selected[0]["state"]["butter_1"]["xyz_m"]
        rise = max(r["state"]["butter_1"]["xyz_m"][2] - anchor[2] for r in selected)
        movement = max(math.dist(r["state"]["butter_1"]["xyz_m"][:2], anchor[:2]) for r in selected)
        gap = min(
            math.dist(r["state"]["butter_1"]["xyz_m"][:2], r["state"]["basket_1"]["xyz_m"][:2])
            for r in selected
        )
        result.update(
            max_rise_after_settle_m=rise,
            max_xy_motion_after_settle_m=movement,
            min_basket_center_xy_gap_m=gap,
        )
        result["pattern"] = (
            "little_object_motion"
            if max(rise, movement) < 0.02
            else "object_near_basket_native_task_incomplete"
            if gap <= 0.05
            else "object_moved_native_task_incomplete"
        )
    if receipt["task_outcome"] == "PASS":
        result["pattern"] = "native_task_completed"
    return result
