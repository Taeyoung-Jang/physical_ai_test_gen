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

import mujoco
import numpy as np
from scipy.spatial.transform import Rotation

from lerobot.robots.unitree_g1.config_unitree_g1 import UnitreeG1Config
from lerobot.robots.unitree_g1.unitree_g1 import UnitreeG1

_ZERO_REMOTE = {"remote.lx": 0.0, "remote.ly": 0.0, "remote.rx": 0.0, "remote.ry": 0.0}

# Kinematic "grasp" via a pre-declared weld equality constraint (pick-and-carry extension beyond
# blueprint §14) — see the constraint's own comment in scene_43dof_with_target.xml for why (no
# hand/finger control exists in this LeRobot integration at all).
GRASP_ATTACH_BODY = "right_wrist_yaw_link"
GRASP_OBJECT_BODY = "navigation_target"
GRASP_EQUALITY_NAME = "grasp_weld"

# Headlessly grid-searched over right_shoulder_pitch/roll + right_elbow (see conversation
# record) for the pose that reaches farthest forward while staying near the pickup pedestal's
# top (z~0.85m) — a standing G1 cannot reach the floor with arm joints alone, hence the pedestal
# in scene_43dof_with_target.xml. Shared here (not just in scripts/run_pickup_smoke.py) so
# control_loop.py's GRASP/RELEASE handling uses the exact same, live-verified pose.
GRASP_REACH_POSE = {
    "kRightShoulderPitch.q": -0.8,
    "kRightShoulderRoll.q": 0.0,
    "kRightShoulderYaw.q": 0.0,
    "kRightElbow.q": 1.4,
    "kRightWristRoll.q": 0.0,
    "kRightWristPitch.q": 0.0,
    "kRightWristYaw.q": 0.0,
}
GRASP_REST_POSE = dict.fromkeys(GRASP_REACH_POSE, 0.0)


@dataclass(frozen=True)
class RobotFrame:
    rgb: np.ndarray
    timestamp_ns: int
    imu_roll: float
    imu_pitch: float
    imu_yaw: float
    base_x: float | None = None
    base_y: float | None = None


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

    def _inner_sim_env(self):
        """The vendored HF-hub sim module's DefaultEnv instance — holds mj_model/mj_data/
        elastic_band. Reaches through several layers that aren't a public API
        (UnitreeG1.sim_env -> gym Env.simulator -> BaseSimulator.sim_env -> DefaultEnv), so
        every caller must treat None as "not available" (e.g. outside simulation mode) rather
        than assume any layer exists.
        """
        sim_env = getattr(self._robot, "sim_env", None)
        simulator = getattr(sim_env, "simulator", None)
        return getattr(simulator, "sim_env", None)

    def _mj_handles(self) -> tuple:
        """(mj_model, mj_data) from the inner sim env, or (None, None) if unreachable — the
        common entry point every privileged-state accessor below builds on."""
        inner_env = self._inner_sim_env()
        mj_model = getattr(inner_env, "mj_model", None)
        mj_data = getattr(inner_env, "mj_data", None)
        if mj_model is None or mj_data is None:
            return None, None
        return mj_model, mj_data

    def _base_xy(self) -> tuple[float, float] | None:
        """Ground-truth (x, y) of the robot's floating base in world frame, read straight from
        MuJoCo (mj_data.qpos[:2]) — used to score navigation episodes against the red-box
        target (blueprint §14.3). This is privileged simulator state a real G1 has no way to
        report (no GPS/mocap on the actual hardware). Returns None if the internals aren't
        reachable rather than raising.
        """
        _, mj_data = self._mj_handles()
        if mj_data is None:
            return None
        return float(mj_data.qpos[0]), float(mj_data.qpos[1])

    def set_lateral_offset(self, offset_m: float) -> bool:
        """Teleports the robot's initial Y position (blueprint §17 Milestone 6: "3개의 초기
        좌우 offset에서 episode 실행"). Must be called right after connect(), before the
        settle-wait / band release — the scene's elastic band holds the robot toward a FIXED
        world point [0, 0, 1] (see the cached sim module's ElasticBand.point), not toward the
        robot's own position. Moving mj_data.qpos alone would have the band's huge spring
        constant (kp_pos=10000) yank the robot straight back toward y=0 during the settle wait,
        both defeating the offset and likely destabilizing the robot. Moving the band's own
        target point in lockstep makes it hold the robot suspended AT the offset instead, so
        releasing the band (key "9") starts the robot standing at the offset exactly like the
        unmodified y=0 case. Returns False (no-op) if the sim internals aren't reachable.
        """
        mj_model, mj_data = self._mj_handles()
        if mj_model is None:
            return False

        mj_data.qpos[1] = offset_m
        mujoco.mj_forward(mj_model, mj_data)

        elastic_band = getattr(self._inner_sim_env(), "elastic_band", None)
        if elastic_band is not None:
            elastic_band.point[1] = offset_m

        return True

    def release_elastic_band(
        self,
        gradual_steps: int = 20,
        decrement: float = 0.05,
        step_dt: float = 0.3,
        hold_s: float = 2.0,
    ) -> bool:
        """Automates what had been a manual step every single run: lowering the scene's
        elastic band (key "7" a few times, then "9" to disable) so the robot settles onto the
        floor and stands on its own. Blocking (uses time.sleep, not asyncio.sleep) — call this
        during setup, before run_episode()'s async loop starts, same as the settle_s wait it
        replaces.

        Lowers `elastic_band.length` gradually (mirroring repeated "7" presses) rather than
        disabling outright from full suspension height — an abrupt full-height drop was
        observed to sometimes destabilize the robot in earlier manual testing (see
        envs/SETUP_NOTES.md and the conversation record). Defaults total ~8s (20 steps * 0.3s +
        2s final hold), matching the settle_s=8.0 duration that was already known to work when
        done by hand — an earlier version of this method used 10 steps * 0.15s (1.5s total),
        which was too fast: the robot toppled (pitch_exceeded) before ever reaching a single
        decision, immediately on the very first live run after this method was added (see
        conversation record). Holds at the fully-lowered-but-still-enabled position for hold_s
        before disabling, so the controller has time to plant the feet under nearly-full support
        before that support is removed, rather than disabling right as lowering finishes.

        Also removes a real source of run-to-run variance we'd been chasing: manual keypress
        timing differed every single run; this replaces it with the same fixed sequence every
        time. Returns False (no-op) if the sim internals aren't reachable.
        """
        elastic_band = getattr(self._inner_sim_env(), "elastic_band", None)
        if elastic_band is None:
            return False

        for _ in range(gradual_steps):
            elastic_band.length -= decrement
            time.sleep(step_dt)
        time.sleep(hold_s)
        elastic_band.enable = False
        return True

    def send_arm_action(self, arm_positions: Mapping[str, float]) -> None:
        """Sends arm joint position targets (pick-and-carry extension beyond blueprint §14)
        while holding zero locomotion input, so the robot stays standing still while the arm
        moves. Keys must be G1_29_JointArmIndex names + '.q', e.g. 'kRightShoulderPitch.q' (see
        lerobot.robots.unitree_g1.g1_utils.G1_29_JointArmIndex) — these get published straight
        to the arm motors by UnitreeG1.send_action(), separately from the locomotion controller.
        """
        action = dict(_ZERO_REMOTE)
        action.update(arm_positions)
        self._robot.send_action(action)

    def try_grasp(self, max_distance_m: float = 0.35) -> bool:
        """Kinematic "grasp" (pick-and-carry extension beyond blueprint §14) — not real
        finger/contact grasping (this LeRobot integration exposes no hand/finger control at
        all, see the module docstring). Computes GRASP_OBJECT_BODY's current pose relative to
        GRASP_ATTACH_BODY and writes it into the scene's pre-declared, initially-inactive weld
        equality constraint, then activates it — the object then moves rigidly with the wrist
        for as long as the constraint stays active. Mechanism verified headlessly (rotating +
        translating carrier, object tracked with no snap on activation, settled naturally on
        release) before being wired in here.

        Returns False (no-op, nothing grasped) if: the scene has no grasp_weld constraint (e.g.
        G1_LOCAL_NAV_SCENE unset, so the plain upstream scene is loaded), sim internals aren't
        reachable, or the object is farther than max_distance_m from the attach body — this
        distance check is the entire "did the hand actually get there" test, standing in for
        the contact test a real hand would need.
        """
        mj_model, mj_data = self._mj_handles()
        if mj_model is None:
            return False

        eq_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_EQUALITY, GRASP_EQUALITY_NAME)
        attach_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_BODY, GRASP_ATTACH_BODY)
        object_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_BODY, GRASP_OBJECT_BODY)
        if eq_id < 0 or attach_id < 0 or object_id < 0:
            return False

        attach_pos = mj_data.xpos[attach_id].copy()
        attach_quat = mj_data.xquat[attach_id].copy()
        object_pos = mj_data.xpos[object_id].copy()
        object_quat = mj_data.xquat[object_id].copy()

        if float(np.linalg.norm(object_pos - attach_pos)) > max_distance_m:
            return False

        attach_quat_neg = np.zeros(4)
        mujoco.mju_negQuat(attach_quat_neg, attach_quat)
        diff = np.zeros(3)
        mujoco.mju_sub3(diff, object_pos, attach_pos)
        rel_pos = np.zeros(3)
        mujoco.mju_rotVecQuat(rel_pos, diff, attach_quat_neg)
        rel_quat = np.zeros(4)
        mujoco.mju_mulQuat(rel_quat, attach_quat_neg, object_quat)

        mj_model.eq_data[eq_id][0:3] = 0.0
        mj_model.eq_data[eq_id][3:6] = rel_pos
        mj_model.eq_data[eq_id][6:10] = rel_quat
        mj_data.eq_active[eq_id] = 1
        return True

    def release_grasp(self) -> bool:
        """Deactivates the grasp weld — the object separates and falls/settles under normal
        physics wherever it was let go, not reverting to its pre-grasp position. Returns False
        if there's no grasp_weld constraint or sim internals aren't reachable."""
        mj_model, mj_data = self._mj_handles()
        if mj_model is None:
            return False
        eq_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_EQUALITY, GRASP_EQUALITY_NAME)
        if eq_id < 0:
            return False
        mj_data.eq_active[eq_id] = 0
        return True

    def is_grasping(self) -> bool:
        mj_model, mj_data = self._mj_handles()
        if mj_model is None:
            return False
        eq_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_EQUALITY, GRASP_EQUALITY_NAME)
        if eq_id < 0:
            return False
        return bool(mj_data.eq_active[eq_id])

    def object_xyz(self, body_name: str = GRASP_OBJECT_BODY) -> tuple[float, float, float] | None:
        """Ground-truth world position of any named MuJoCo body (default: the pickup target) —
        used by diagnostics/smoke-test scripts to confirm the object actually moves with the
        robot while grasped and stays where it's dropped after release."""
        mj_model, mj_data = self._mj_handles()
        if mj_model is None:
            return None
        body_id = mujoco.mj_name2id(mj_model, mujoco.mjtObj.mjOBJ_BODY, body_name)
        if body_id < 0:
            return None
        return float(mj_data.xpos[body_id][0]), float(mj_data.xpos[body_id][1]), float(mj_data.xpos[body_id][2])

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

        # obs["imu.rpy.*"] comes straight from the sim bridge's own rpy field, which is
        # confirmed broken in simulation mode: roll stayed exactly 0.0 across 10 reads where
        # the quaternion clearly showed real, changing rotation (scripts/diag_imu.py output,
        # 2026-08-16 — quat.x/z moved from ~0.003/-0.0004 to ~0.049/-0.114 while rpy.roll never
        # left 0.0). This is safety-critical: check_frame_safety() uses roll/pitch to detect
        # the robot tipping over, so a stuck 0.0 silently disables that check. Computed from
        # the quaternion instead, which is confirmed live.
        roll, pitch, yaw = 0.0, 0.0, 0.0
        qw = obs.get("imu.quat.w")
        if qw is not None:
            qx = obs.get("imu.quat.x", 0.0)
            qy = obs.get("imu.quat.y", 0.0)
            qz = obs.get("imu.quat.z", 0.0)
            roll, pitch, yaw = Rotation.from_quat([qx, qy, qz, qw]).as_euler("xyz")

        base_xy = self._base_xy()

        return RobotFrame(
            rgb=rgb if rgb is not None else np.zeros((1, 1, 3), dtype=np.uint8),
            timestamp_ns=timestamp_ns,
            imu_roll=float(roll),
            imu_pitch=float(pitch),
            imu_yaw=float(yaw),
            base_x=base_xy[0] if base_xy is not None else None,
            base_y=base_xy[1] if base_xy is not None else None,
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
