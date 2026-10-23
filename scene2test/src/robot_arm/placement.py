"""Initialization-only object placement; never overrides physics during a rollout."""

import json
from pathlib import Path

OBJECTS = {"bowl": "akita_black_bowl_1", "plate": "plate_1"}
AXES = ("bowl_x", "bowl_y", "plate_x", "plate_y")


def checked(values, bounds):
    import math

    if set(values) != set(AXES) or set(bounds) != set(AXES):
        raise ValueError("exactly bowl_x/bowl_y/plate_x/plate_y required")
    for name in AXES:
        lo, hi = bounds[name]
        v = values[name]
        if (
            type(v) not in (int, float)
            or not math.isfinite(v)
            or not math.isfinite(lo)
            or not math.isfinite(hi)
            or not lo < hi
            or not lo <= v <= hi
        ):
            raise ValueError("position outside shared bounds: " + name)
    return {k: float(values[k]) for k in AXES}


def snapshot(control):
    raw = control.env
    return {
        name: {
            "xyz_m": control.sim.data.body_xpos[body].tolist(),
            "quat_wxyz": control.sim.data.body_xquat[body].tolist(),
        }
        for name, body in raw.obj_body_id.items()
    }


def apply(control, values, background=None):
    """Set free-joint XY before first action; preserve sampled Z/orientation/others."""
    import numpy as np

    raw, sim = control.env, control.sim
    before = snapshot(control)
    offset = np.asarray(raw.workspace_offset)
    background = background or {}
    targets = {
        name: [values[short + "_x"], values[short + "_y"]] for short, name in OBJECTS.items()
    }
    targets.update(background)
    moved = {}
    for name, xy in targets.items():
        obj = raw.objects_dict[name]
        qpos = sim.data.get_joint_qpos(obj.joints[-1]).copy()
        qpos[:2] = offset[:2] + xy
        sim.data.set_joint_qpos(obj.joints[-1], qpos)
        moved[name] = {sim.model.geom_name2id(g) for g in obj.contact_geoms}
    sim.forward()
    after = snapshot(control)
    problems = []
    for name, xy in targets.items():
        desired = offset[:2] + xy
        if not np.allclose(after[name]["xyz_m"][:2], desired, atol=1e-7, rtol=0):
            problems.append("pose_mismatch:" + name)
        # Conservative footprint sphere for each collision geometry; table-local frame.
        for gid in moved[name]:
            center = sim.data.geom_xpos[gid][:2] - offset[:2]
            radius = float(sim.model.geom_rbound[gid])
            if np.any(np.abs(center) + radius > np.asarray(raw.table_full_size[:2]) / 2):
                problems.append("outside_table:" + name)
    selected = set().union(*moved.values())
    contacts = []
    for i in range(sim.data.ncon):
        contact = sim.data.contact[i]
        a, b = int(contact.geom1), int(contact.geom2)
        if a not in selected and b not in selected:
            continue
        names = [sim.model.geom_id2name(g) or "" for g in (a, b)]
        same_object = any(a in ids and b in ids for ids in moved.values())
        support = any(n.startswith("table") or n.startswith("main_table") for n in names)
        if not same_object and not support and float(contact.dist) < -1e-6:
            contacts.append({"geoms": names, "distance_m": float(contact.dist)})
    if contacts:
        problems.append("initial_object_penetration")
    if control.check_success():
        problems.append("already_successful_initial_state")
    for name in before.keys() - targets.keys():
        if before[name] != after[name]:
            problems.append("unrequested_object_changed:" + name)
    return {
        "coordinate_frame": "table workspace_offset + requested XY, metres",
        "requested": values,
        "fixed_background_positions": background,
        "workspace_offset_m": offset.tolist(),
        "before": before,
        "after": after,
        "problems": sorted(set(problems)),
        "penetrations": contacts,
        "valid": not problems,
        "claim": "Initial geometry only; not reachability or policy success proof.",
    }


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def run_episode(config, candidate, directory):
    """Process-local factory override; upstream policy/evaluator files remain untouched."""
    import os
    import sys

    os.environ["LIBERO_CONFIG_PATH"] = config["robot"]["libero_config_path"]
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, config["robot"]["upstream_root"])
    import gymnasium as gym
    from gr00t.eval import rollout_policy as rollout
    from gr00t.eval.sim.LIBERO.libero_env import LiberoEnv, register_libero_envs

    values = checked(candidate["positions"], config["bounds"])
    reset_count = 0

    class PlacedEnv(LiberoEnv):
        def reset(self, seed=None, options=None):
            nonlocal reset_count
            reset_count += 1
            if reset_count > 1:
                # Gymnasium 0.29 SyncVectorEnv auto-resets at terminal. Return the
                # cached final observation without randomizing or executing another task.
                self._terminal_reset = True
                return self._last_observation, {"success": self._env.check_success()}
            # Avoid LIBERO ControlEnv.reset's unbounded RandomizationError loop.
            if seed is not None:
                self._env.seed(config["background_seed"])
            self._env.env.reset()
            audit = apply(self._env, values, config["background_positions"])
            save(directory / "initial_state.json", audit)
            if not audit["valid"]:
                raise ValueError("invalid initial placement: " + repr(audit["problems"]))
            state = self._env.get_sim_state().tolist()
            save(directory / "initial_sim_state.json", {"state": state})
            self._env.env._update_observables(force=True)
            obs = self._env.env._get_observations(force_update=True)
            self._last_observation = self._process_observation(obs)
            self._terminal_reset = False
            return self._last_observation, {"success": self._env.check_success()}

        def step(self, action):
            if self._terminal_reset:
                raise RuntimeError("unexpected extra episode action")
            result = super().step(action)
            self._last_observation = result[0]
            row = {"objects": snapshot(self._env), "success": bool(result[4]["success"])}
            with (directory / "trace.jsonl").open("a") as stream:
                stream.write(json.dumps(row, allow_nan=False) + "\n")
            return result

    def factory(name):
        def make():
            register_libero_envs()
            spec = gym.spec(name)
            return PlacedEnv(**spec.kwargs)

        return make

    rollout.get_libero_env_fn = factory
    result = rollout.run_gr00t_sim_policy(
        env_name=config["robot"]["env_name"],
        n_episodes=1,
        max_episode_steps=config["robot"]["max_episode_steps"],
        model_path=config["robot"]["model_path"],
        n_envs=1,
        n_action_steps=config["robot"]["n_action_steps"],
        video_dir=str(directory / "videos"),
        seed=candidate["scene_seed"],
    )
    if len(result[1]) != 1:
        raise RuntimeError("missing upstream outcome")
    trace = directory / "trace.jsonl"
    last = json.loads(trace.read_text().splitlines()[-1])
    success = bool(result[1][0])
    return {
        "status": "VALID",
        "task_outcome": "PASS" if success else "FAIL",
        "steps": [int(n) for n in result[2]["episode_lengths"]],
        "final_objects": last["objects"],
        "scene_seed": candidate["scene_seed"],
        "success_rule": "unmodified LIBERO check_success",
    }
