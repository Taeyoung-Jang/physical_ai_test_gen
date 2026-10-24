"""Real LIBERO + one CPU control step with policy/camera test doubles, never a rollout result."""

import json
import os
import sys
import types
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "src"))
from robot_arm import task_comparison as x  # noqa: E402
from robot_arm import task_environments as envs  # noqa: E402

config = json.loads((PROJECT / "config/robot_arm_object_goal_comparison.json").read_text())
os.environ["LIBERO_CONFIG_PATH"] = config["tasks"]["object"][0]["robot"]["libero_config_path"]
sys.path.insert(0, config["tasks"]["object"][0]["robot"]["upstream_root"])
import numpy as np  # noqa: E402
from libero.libero.envs.env_wrapper import ControlEnv  # noqa: E402

# Stub imports before the new adapter imports GR00T: no policy or GPU libraries loaded.
for name in (
    "gr00t",
    "gr00t.eval",
    "gr00t.eval.rollout_policy",
    "gr00t.eval.sim",
    "gr00t.eval.sim.LIBERO",
    "gr00t.eval.sim.LIBERO.libero_env",
):
    sys.modules[name] = types.ModuleType(name)
rollout = sys.modules["gr00t.eval.rollout_policy"]
libero_module = sys.modules["gr00t.eval.sim.LIBERO.libero_env"]
gym = types.ModuleType("gymnasium")
sys.modules["gymnasium"] = gym


class CameraDoubleEnv:
    def __init__(self, task_bddl_file, task_description):
        self._env = ControlEnv(task_bddl_file, use_camera_obs=False, has_offscreen_renderer=False)

    def _process_observation(self, obs):
        return obs

    def step(self, action):
        obs, reward, done, info = self._env.step(action)
        info["success"] = self._env.check_success()
        return obs, reward, done, False, info

    def close(self):
        self._env.close()


libero_module.LiberoEnv = CameraDoubleEnv
libero_module.register_libero_envs = lambda: None


def fake_policy_rollout(**kwargs):
    env = rollout.get_libero_env_fn(kwargs["env_name"])()
    try:
        env.reset(seed=kwargs["seed"])
        result = env.step(np.zeros(7))
        # Exercise the terminal auto-reset guard without executing a second episode.
        last = env.reset()
        assert last[1]["success"] == result[4]["success"]
        return kwargs["env_name"], [result[4]["success"]], {"episode_lengths": [1]}
    finally:
        env.close()


rollout.run_gr00t_sim_policy = fake_policy_rollout
for task in ("object", "goal"):
    d = config["tasks"][task][0]
    suite, name = envs.TASKS[task]
    bddl = (
        Path(d["robot"]["upstream_root"])
        / "external_dependencies/LIBERO/libero/libero/bddl_files"
        / suite
        / (name + ".bddl")
    )
    gym.spec = lambda _, bddl=bddl: types.SimpleNamespace(
        kwargs={"task_bddl_file": str(bddl), "task_description": "test double"}
    )
    folder = Path(sys.argv[1]) / task
    folder.mkdir()
    p = {a: sum(v) / 2 for a, v in d["domain"].items()}
    c = x.candidate(d, p, d["seeds"][0], 0, "CPU test double")
    result = envs.run_episode(d, c, folder)
    assert result["steps"] == [1]
    rows = [json.loads(s) for s in (folder / "physics.jsonl").read_text().splitlines()]
    assert len(rows) > 1
    assert envs.measure(folder, result, task)["status"] == "COMPLETE"
    assert "torch" not in sys.modules
    print("CPU_PROBE_OK", task, len(rows), flush=True)
