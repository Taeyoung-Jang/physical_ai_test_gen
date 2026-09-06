"""Headless adapter for the released GR00T-WBC G1 balance and walk policies."""

from __future__ import annotations

import collections
import os
from pathlib import Path
from typing import Literal

import mujoco
import numpy as np
import onnxruntime as ort
import yaml


class G1OnnxController:
    """Run the native 29-DoF G1 balance or walking ONNX policy."""

    def __init__(
        self,
        groot_root: Path,
        mode: Literal["balance", "walk"],
        command: np.ndarray | None = None,
        *,
        model=None,
    ) -> None:
        resource_root = groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1"
        config = yaml.safe_load((resource_root / "g1_gear_wbc.yaml").read_text())
        for key in ("kps", "kds", "default_angles", "cmd_scale", "cmd_init"):
            config[key] = np.asarray(config[key], dtype=np.float32)
        policy_name = (
            "GR00T-WholeBodyControl-Balance.onnx"
            if mode == "balance"
            else "GR00T-WholeBodyControl-Walk.onnx"
        )
        self.mode = mode
        self.config = config
        self.model = (
            model
            if model is not None
            else mujoco.MjModel.from_xml_path(str(resource_root / "g1_gear_wbc.xml"))
        )
        self.data = mujoco.MjData(self.model)
        requested_provider = os.getenv("SIM_SERVER_ONNX_PROVIDER", "cuda").lower()
        available = ort.get_available_providers()
        if requested_provider == "cuda":
            if "CUDAExecutionProvider" not in available:
                raise RuntimeError("CUDAExecutionProvider is required but unavailable")
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        elif requested_provider == "cpu":
            providers = ["CPUExecutionProvider"]
        else:
            raise ValueError("SIM_SERVER_ONNX_PROVIDER must be 'cuda' or 'cpu'")
        self.session = ort.InferenceSession(
            str(resource_root / "policy" / policy_name), providers=providers
        )
        self.execution_provider = self.session.get_providers()[0]
        if requested_provider == "cuda" and self.execution_provider != "CUDAExecutionProvider":
            raise RuntimeError("ONNX policy failed to initialize on CUDAExecutionProvider")
        self.input_name = self.session.get_inputs()[0].name
        self.command = np.asarray(
            command if command is not None else config["cmd_init"], dtype=np.float32
        )
        self.action = np.zeros(config["num_actions"], dtype=np.float32)
        self.target = config["default_angles"].copy()
        self.history = collections.deque(
            [np.zeros(86, dtype=np.float32)] * config["obs_history_len"],
            maxlen=config["obs_history_len"],
        )
        self.counter = 0

    def step(self) -> None:
        config = self.config
        action_count = config["num_actions"]
        q = self.data.qpos[7 : 7 + action_count]
        dq = self.data.qvel[6 : 6 + action_count]
        self.data.ctrl[:action_count] = (self.target - q) * config["kps"] - dq * config["kds"]
        if self.model.nu > action_count:
            self.data.ctrl[action_count:] = (
                -self.data.qpos[7 + action_count : 7 + self.model.nu] * 100.0
                - self.data.qvel[6 + action_count : 6 + self.model.nu] * 0.5
            )
        mujoco.mj_step(self.model, self.data)
        self.counter += 1
        if self.counter % config["control_decimation"] == 0:
            observation = self._observation()
            self.history.append(observation)
            policy_input = np.concatenate(self.history)[None, :].astype(np.float32)
            self.action = self.session.run(None, {self.input_name: policy_input})[0][0]
            self.target = self.action * config["action_scale"] + config["default_angles"]

    def _observation(self) -> np.ndarray:
        config = self.config
        joint_count = self.model.nu
        defaults = np.zeros(joint_count, dtype=np.float32)
        defaults[: config["num_actions"]] = config["default_angles"]
        observation = np.zeros(86, dtype=np.float32)
        observation[0:3] = self.command * config["cmd_scale"]
        observation[3] = config["height_cmd"]
        observation[4:7] = config["rpy_cmd"]
        observation[7:10] = self.data.qvel[3:6] * config["ang_vel_scale"]
        observation[10:13] = _gravity_orientation(self.data.qpos[3:7])
        observation[13 : 13 + joint_count] = (
            self.data.qpos[7 : 7 + joint_count] - defaults
        ) * config["dof_pos_scale"]
        observation[13 + joint_count : 13 + 2 * joint_count] = (
            self.data.qvel[6 : 6 + joint_count] * config["dof_vel_scale"]
        )
        observation[13 + 2 * joint_count :] = self.action
        return observation


def _gravity_orientation(quaternion: np.ndarray) -> np.ndarray:
    w, x, y, z = quaternion
    conjugate = np.asarray([w, -x, -y, -z])
    cw, cx, cy, cz = conjugate
    return np.asarray(
        [
            -2.0 * (cx * cz + cw * cy),
            -2.0 * (cy * cz - cw * cx),
            -(cw * cw - cx * cx - cy * cy + cz * cz),
        ],
        dtype=np.float32,
    )
