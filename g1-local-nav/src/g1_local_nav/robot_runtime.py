"""Programmatic G1 control (blueprint §9) — replaces the gamepad/keyboard teleop CLI.

`lerobot-teleoperate --teleop.type=keyboard` cannot move G1: LeRobot's default
teleop_action_processor is a bare passthrough (IdentityProcessorStep, see
third_party/lerobot/src/lerobot/processor/factory.py) that never translates keyboard keys into
the `remote.lx/ly/rx/ry` axes UnitreeG1.send_action() expects. Only real Unitree remote hardware
speaks that protocol natively. G1Runtime calls robot.send_action() directly instead, which is
the only way to move the simulated robot without that hardware.

Must be driven from a script run under `mjpython`, not plain `python` — macOS's
mujoco.viewer.launch_passive() (used internally by the `is_simulation=True` env) requires it.
See envs/SETUP_NOTES.md.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Mapping

import numpy as np

from lerobot.robots.unitree_g1.config_unitree_g1 import UnitreeG1Config
from lerobot.robots.unitree_g1.unitree_g1 import UnitreeG1

_ZERO_REMOTE = {"remote.lx": 0.0, "remote.ly": 0.0, "remote.rx": 0.0, "remote.ry": 0.0}


@dataclass(frozen=True)
class RobotFrame:
    rgb: np.ndarray
    timestamp_ns: int
    imu_roll: float
    imu_pitch: float
    imu_yaw: float


class G1Runtime:
    """Thin wrapper around LeRobot's UnitreeG1 for simulation-mode programmatic control."""

    def __init__(self, camera_name: str = "global_view", cameras: dict | None = None):
        self._camera_name = camera_name
        config = UnitreeG1Config(
            is_simulation=True,
            controller="GrootLocomotionController",
            cameras=cameras or {},
        )
        self._robot = UnitreeG1(config)
        self._connected = False
        self._epoch_ref = 0.0
        self._perf_ref = 0.0

    def connect(self) -> None:
        self._robot.connect()
        self._connected = True
        # Reference pair to convert camera capture times (time.perf_counter(), monotonic,
        # arbitrary zero point) into epoch nanoseconds. Captured once, right after connect,
        # so downstream age math (epoch_now - frame.timestamp_ns) means something — see the
        # frame-age bug this replaced: stamping read-time as "the" timestamp always gives a
        # frame age of ~0, which is meaningless.
        self._epoch_ref = time.time()
        self._perf_ref = time.perf_counter()

    def latest_frame(self) -> RobotFrame:
        obs = self._robot.get_observation()
        rgb = obs.get(self._camera_name)

        camera = self._robot._cameras.get(self._camera_name) if hasattr(self._robot, "_cameras") else None
        capture_perf = getattr(camera, "latest_timestamp", None)
        if capture_perf is not None:
            capture_epoch = self._epoch_ref + (capture_perf - self._perf_ref)
            timestamp_ns = int(capture_epoch * 1e9)
        else:
            # No camera configured (or it hasn't captured a frame yet) — nothing to timestamp
            # against, so fall back to read-time. Age computed from this will read ~0; that's
            # expected in this case, not the bug the epoch-ref path above fixes.
            timestamp_ns = time.time_ns()

        return RobotFrame(
            rgb=rgb if rgb is not None else np.zeros((1, 1, 3), dtype=np.uint8),
            timestamp_ns=timestamp_ns,
            imu_roll=obs.get("imu.rpy.roll", 0.0),
            imu_pitch=obs.get("imu.rpy.pitch", 0.0),
            imu_yaw=obs.get("imu.rpy.yaw", 0.0),
        )

    def send_remote(self, command: Mapping[str, float]) -> None:
        self._robot.send_action(dict(command))

    def stop(self) -> None:
        if self._connected:
            self._robot.send_action(dict(_ZERO_REMOTE))

    def reset(self) -> None:
        # NOTE: this does not reset simulation state (elastic band, robot pose) yet — it only
        # re-sends STOP. A real episode reset (teleport to home pose, re-arm elastic band) is
        # deferred to Milestone 5 where episode boundaries actually matter. Documented gap, not
        # an oversight.
        self.stop()

    def close(self) -> None:
        self.stop()
        if self._connected:
            self._robot.disconnect()
            self._connected = False

    def __enter__(self) -> "G1Runtime":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # Always STOP + disconnect on the way out, exception or not (blueprint §12.1, §20 rule 8).
        self.close()
