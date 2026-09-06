from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
from dataclasses import dataclass, field
from pathlib import Path

from failure_client.contracts import (
    ArtifactRef,
    ExecutionSummary,
    RemoteJobState,
    RolloutRequest,
    RolloutResult,
    StandardEvent,
)


def _artifact(job_id: str, path: Path, kind: str) -> ArtifactRef:
    payload = path.read_bytes()
    return ArtifactRef(
        artifact_id=f"{job_id}:{path.name}",
        kind=kind,
        format=path.suffix.lstrip(".") or "jsonl",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _render_settings() -> tuple[int, int, int]:
    width = int(os.getenv("SIM_SERVER_RENDER_WIDTH", "640"))
    height = int(os.getenv("SIM_SERVER_RENDER_HEIGHT", "480"))
    fps = int(os.getenv("SIM_SERVER_RENDER_FPS", "20"))
    if width <= 0 or height <= 0 or fps <= 0:
        raise ValueError("render width, height, and FPS must be positive")
    return width, height, fps


def _quaternion_rpy(quaternion) -> tuple[float, float, float]:
    """Return intrinsic roll, pitch, yaw for a MuJoCo wxyz quaternion."""
    import numpy as np

    w, x, y, z = quaternion
    roll = np.arctan2(2.0 * (w * x + y * z), 1.0 - 2.0 * (x * x + y * y))
    pitch = np.arcsin(np.clip(2.0 * (w * y - z * x), -1.0, 1.0))
    yaw = np.arctan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))
    return float(roll), float(pitch), float(yaw)


@dataclass
class LocomotionMetrics:
    """Online stability, tracking, effort, and contact-slip measurements."""

    command: object
    timestep_s: float
    warmup_s: float = 1.0
    sample_count: int = 0
    velocity_error_sq: object = field(default=None)
    velocity_sum: object = field(default=None)
    max_abs_roll_rad: float = 0.0
    max_abs_pitch_rad: float = 0.0
    torque_sq_sum: float = 0.0
    torque_sample_count: int = 0
    effort_sample_count: int = 0
    max_abs_torque_nm: float = 0.0
    mechanical_power_sum_w: float = 0.0
    minimum_base_height_m: float = float("inf")
    foot_slip_sq_sum: float = 0.0
    foot_slip_sample_count: int = 0
    max_foot_slip_speed_mps: float = 0.0

    def __post_init__(self) -> None:
        import numpy as np

        self.velocity_error_sq = np.zeros(3, dtype=float)
        self.velocity_sum = np.zeros(3, dtype=float)

    def update(self, model, data) -> None:
        import mujoco
        import numpy as np

        roll, pitch, _ = _quaternion_rpy(data.qpos[3:7])
        self.max_abs_roll_rad = max(self.max_abs_roll_rad, abs(roll))
        self.max_abs_pitch_rad = max(self.max_abs_pitch_rad, abs(pitch))
        self.minimum_base_height_m = min(self.minimum_base_height_m, float(data.qpos[2]))

        torque = np.asarray(data.ctrl, dtype=float)
        joint_velocity = np.asarray(data.qvel[6 : 6 + model.nu], dtype=float)
        self.torque_sq_sum += float(np.dot(torque, torque))
        self.torque_sample_count += torque.size
        self.effort_sample_count += 1
        self.max_abs_torque_nm = max(self.max_abs_torque_nm, float(np.max(np.abs(torque))))
        self.mechanical_power_sum_w += float(np.sum(np.abs(torque * joint_velocity)))

        if data.time >= self.warmup_s:
            rotation = np.empty(9, dtype=float)
            mujoco.mju_quat2Mat(rotation, data.qpos[3:7])
            body_velocity = rotation.reshape(3, 3).T @ np.asarray(data.qvel[:3])
            body_angular_velocity = np.asarray(data.qvel[3:6])
            measured = np.asarray([body_velocity[0], body_velocity[1], body_angular_velocity[2]])
            error = measured - self.command
            self.velocity_error_sq += error * error
            self.velocity_sum += measured
            self.sample_count += 1

        from .path_tracking import contact_slip_speeds

        for speed in contact_slip_speeds(model, data):
            self.foot_slip_sq_sum += speed * speed
            self.foot_slip_sample_count += 1
            self.max_foot_slip_speed_mps = max(self.max_foot_slip_speed_mps, speed)

    def result(self) -> dict[str, float | None]:
        import numpy as np

        divisor = max(self.sample_count, 1)
        velocity_rmse = np.sqrt(self.velocity_error_sq / divisor)
        velocity_mean = self.velocity_sum / divisor
        return {
            "tracking_sample_count": self.sample_count,
            "foot_contact_sample_count": self.foot_slip_sample_count,
            "minimum_base_height_m": self.minimum_base_height_m
            if self.effort_sample_count
            else None,
            "maximum_abs_roll_rad": self.max_abs_roll_rad,
            "maximum_abs_pitch_rad": self.max_abs_pitch_rad,
            "mean_forward_velocity_mps": float(velocity_mean[0]),
            "mean_lateral_velocity_mps": float(velocity_mean[1]),
            "mean_yaw_rate_radps": float(velocity_mean[2]),
            "forward_velocity_rmse_mps": float(velocity_rmse[0]),
            "lateral_velocity_rmse_mps": float(velocity_rmse[1]),
            "yaw_rate_rmse_radps": float(velocity_rmse[2]),
            "joint_torque_rms_nm": ((self.torque_sq_sum / max(self.torque_sample_count, 1)) ** 0.5),
            "maximum_abs_joint_torque_nm": self.max_abs_torque_nm,
            "mean_absolute_mechanical_power_w": self.mechanical_power_sum_w
            / max(self.effort_sample_count, 1),
            "foot_contact_slip_rms_mps": (
                self.foot_slip_sq_sum / max(self.foot_slip_sample_count, 1)
            )
            ** 0.5,
            "maximum_foot_contact_slip_mps": self.max_foot_slip_speed_mps,
        }


class RolloutRecorder:
    """Stream a complete MP4 and retain a bounded GIF preview."""

    MAX_GIF_FRAMES = 120

    def __init__(self, model, output: Path, duration_s: float) -> None:
        import imageio.v2 as imageio
        import mujoco

        self.imageio = imageio
        self.width, self.height, self.fps = _render_settings()
        self.frame_period = 1.0 / self.fps
        self.next_frame_time = 0.0
        self.renderer = mujoco.Renderer(model, height=self.height, width=self.width)
        self.camera = mujoco.MjvCamera()
        mujoco.mjv_defaultCamera(self.camera)
        self.camera.type = mujoco.mjtCamera.mjCAMERA_FREE
        self.camera.lookat[:] = [0.0, 0.0, 0.8]
        self.camera.distance = 3.0
        self.camera.azimuth = 135.0
        self.camera.elevation = -20.0
        self.mp4_path = output / "rollout.mp4"
        self.gif_path = output / "rollout.gif"
        self.thumbnail_path = output / "thumbnail.png"
        self.writer = imageio.get_writer(
            self.mp4_path,
            fps=self.fps,
            codec="libx264",
            quality=8,
            macro_block_size=None,
        )
        expected_frames = max(1, int(duration_s * self.fps) + 1)
        self.gif_stride = max(1, (expected_frames + self.MAX_GIF_FRAMES - 1) // self.MAX_GIF_FRAMES)
        self.gif_frames = []
        self.frame_count = 0

    def capture(self, data, *, force: bool = False) -> None:
        if not force and data.time + 1e-12 < self.next_frame_time:
            return
        self.camera.lookat[:2] = data.qpos[:2]
        self.renderer.update_scene(data, camera=self.camera)
        frame = self.renderer.render().copy()
        self.writer.append_data(frame)
        if self.frame_count == 0:
            self.imageio.imwrite(self.thumbnail_path, frame)
        if self.frame_count % self.gif_stride == 0:
            self.gif_frames.append(frame)
        self.frame_count += 1
        self.next_frame_time += self.frame_period

    def close(self) -> None:
        self.writer.close()
        self.renderer.close()
        self.imageio.mimsave(self.gif_path, self.gif_frames, fps=self.fps, loop=0)


def run_groot(request: RolloutRequest, output: Path, groot_root: Path) -> RolloutResult:
    if platform.system() == "Linux":
        os.environ.setdefault("MUJOCO_GL", "egl")

    import mujoco
    import numpy as np
    import yaml

    learned_controllers = {"groot_balance": "balance", "groot_locomotion": "walk"}
    controller_mode = learned_controllers.get(request.resources.controller.id)
    policy_controller = None
    if controller_mode:
        from .groot_locomotion import G1OnnxController

        parameters = request.task.parameters
        command = np.asarray(
            [
                parameters.get("linear_velocity_x", 0.3 if controller_mode == "walk" else 0.0),
                parameters.get("linear_velocity_y", 0.0),
                parameters.get("yaw_rate", 0.0),
            ],
            dtype=np.float32,
        )
        policy_controller = G1OnnxController(groot_root, controller_mode, command)
        model = policy_controller.model
        data = policy_controller.data
        model.opt.timestep = request.execution.physics_timestep_s or 0.005
    else:
        scene = groot_root / "decoupled_wbc/control/robot_model/model_data/g1/scene_43dof.xml"
        config_path = (
            groot_root / "decoupled_wbc/control/main/teleop/configs/g1_29dof_gear_wbc.yaml"
        )
        config = yaml.safe_load(config_path.read_text())
        model = mujoco.MjModel.from_xml_path(str(scene))
        data = mujoco.MjData(model)
        model.opt.timestep = request.execution.physics_timestep_s or float(config["SIMULATE_DT"])
        if model.nkey:
            mujoco.mj_resetDataKeyframe(model, data, 0)
    external_forces = []
    applied_dynamics = []
    for operation in request.interventions:
        if operation.kind == "dynamics.set_friction":
            coefficient = float(operation.parameters["coefficient"])
            model.geom_friction[:, 0] = coefficient
            applied_dynamics.append({"kind": operation.kind, "coefficient": coefficient})
            mujoco.mj_forward(model, data)
            continue
        if operation.kind == "dynamics.apply_external_force":
            body_name = str(operation.parameters.get("body_name", "pelvis"))
            body_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, body_name)
            if body_id < 0:
                raise ValueError(f"unknown external-force body: {body_name}")
            specification = {
                "kind": operation.kind,
                "body_name": body_name,
                "body_id": body_id,
                "force_n": np.asarray(operation.parameters["force_n"], dtype=float),
                "start_time_s": float(operation.parameters.get("start_time_s", 0.0)),
                "duration_s": float(operation.parameters["duration_s"]),
            }
            external_forces.append(specification)
            applied_dynamics.append(
                {
                    **specification,
                    "force_n": specification["force_n"].tolist(),
                }
            )
            continue
        if operation.kind == "robot_initial_state.set_spawn" or (
            operation.operation_id == "set_robot_spawn" and operation.kind == "robot_initial_state"
        ):
            position = operation.parameters.get("position_m")
            quaternion = operation.parameters.get("quaternion_wxyz")
            if position is not None:
                data.qpos[:3] = np.asarray(position, dtype=float)
            if quaternion is not None:
                data.qpos[3:7] = np.asarray(quaternion, dtype=float)
            mujoco.mj_forward(model, data)
    initial_position = data.qpos[:3].copy()
    initial_rpy = _quaternion_rpy(data.qpos[3:7])
    from .path_tracking import path_errors, supervised_command

    nominal_command = policy_controller.command.copy() if policy_controller else None
    path_hold = request.task.parameters.get("path_hold", False)
    maximum_cross_track = maximum_heading_error = 0.0
    if policy_controller is None:
        target = data.qpos[7 : 7 + model.nu].copy()
        kp = np.asarray(config["MOTOR_KP"], dtype=float)
        kd = np.asarray(config["MOTOR_KD"], dtype=float)
        if model.nu > kp.size:
            kp = np.pad(kp, (0, model.nu - kp.size), constant_values=20.0)
            kd = np.pad(kd, (0, model.nu - kd.size), constant_values=1.0)
    state_path, action_path, contact_path = (
        output / "state_trajectory.jsonl",
        output / "action_trajectory.jsonl",
        output / "contacts.jsonl",
    )
    duration = request.execution.maximum_duration_s
    events: list[StandardEvent] = []
    recorder = (
        RolloutRecorder(model, output, duration) if request.recording.video != "never" else None
    )
    fallen = False
    termination_reason = "MAX_DURATION"
    completed_steps = 0
    maximum_steps = max(1, int(np.ceil(duration / model.opt.timestep)))
    locomotion_metrics = (
        LocomotionMetrics(policy_controller.command, model.opt.timestep)
        if policy_controller is not None
        else None
    )
    try:
        with (
            state_path.open("w") as states,
            action_path.open("w") as actions,
            contact_path.open("w") as contacts,
        ):
            if recorder:
                recorder.capture(data, force=True)
            for _ in range(maximum_steps):
                previous_time = float(data.time)
                data.xfrc_applied[:] = 0.0
                for force in external_forces:
                    force_end = force["start_time_s"] + force["duration_s"]
                    if force["start_time_s"] <= data.time < force_end:
                        data.xfrc_applied[force["body_id"], :3] += force["force_n"]
                if policy_controller:
                    if path_hold:
                        cross_track, heading_error = path_errors(
                            data.qpos[:3], data.qpos[3:7], initial_position, initial_rpy[2]
                        )
                        policy_controller.command = supervised_command(
                            nominal_command, cross_track, heading_error
                        )
                    policy_controller.step()
                else:
                    q = data.qpos[7 : 7 + model.nu]
                    dq = data.qvel[6 : 6 + model.nu]
                    data.ctrl[:] = kp[: model.nu] * (target - q) - kd[: model.nu] * dq
                    mujoco.mj_step(model, data)
                completed_steps += 1
                finite_state = bool(
                    np.all(np.isfinite(data.qpos))
                    and np.all(np.isfinite(data.qvel))
                    and np.all(np.isfinite(data.ctrl))
                )
                time_advanced = float(data.time) > previous_time
                if not finite_state or not time_advanced:
                    termination_reason = "NUMERICAL_INSTABILITY"
                    events.append(
                        StandardEvent(
                            event_type="NUMERICAL_INSTABILITY",
                            timestamp_s=previous_time,
                            measurements={
                                "finite_state": finite_state,
                                "time_advanced": time_advanced,
                                "step_index": completed_steps,
                            },
                        )
                    )
                    break
                states.write(
                    json.dumps(
                        {
                            "time_s": data.time,
                            "qpos": data.qpos.tolist(),
                            "qvel": data.qvel.tolist(),
                        }
                    )
                    + "\n"
                )
                actions.write(
                    json.dumps(
                        {
                            "time_s": data.time,
                            "ctrl": data.ctrl.tolist(),
                            "command": policy_controller.command.tolist()
                            if policy_controller
                            else None,
                        }
                    )
                    + "\n"
                )
                for index in range(data.ncon):
                    contact = data.contact[index]
                    contacts.write(
                        json.dumps(
                            {
                                "time_s": data.time,
                                "geom1": int(contact.geom1),
                                "geom2": int(contact.geom2),
                                "position_m": contact.pos.tolist(),
                            }
                        )
                        + "\n"
                    )
                base_height = float(data.qpos[2])
                if not fallen and base_height < 0.45:
                    fallen = True
                    events.append(
                        StandardEvent(
                            event_type="BASE_HEIGHT_THRESHOLD_CROSSED",
                            timestamp_s=float(data.time),
                            measurements={"base_height_m": base_height, "threshold_m": 0.45},
                        )
                    )
                if locomotion_metrics:
                    # Synchronize kinematics with the integrated state for contact-point metrics.
                    mujoco.mj_forward(model, data)
                    locomotion_metrics.command = policy_controller.command.copy()
                    locomotion_metrics.update(model, data)
                cross_track, heading_error = path_errors(
                    data.qpos[:3], data.qpos[3:7], initial_position, initial_rpy[2]
                )
                maximum_cross_track = max(maximum_cross_track, abs(cross_track))
                maximum_heading_error = max(maximum_heading_error, abs(heading_error))
                if recorder:
                    recorder.capture(data)
    finally:
        if recorder:
            recorder.close()
    job_id = output.name
    reproduction = {
        "job_id": job_id,
        "resolved_resources": request.resources.model_dump(mode="json"),
        "runtime": {
            "backend": "groot_mujoco",
            "python_version": platform.python_version(),
            "mujoco_version": mujoco.__version__,
            "groot_root": str(groot_root),
        },
        "randomness": {"master_seed": request.execution.seed},
        "execution": {"physics_timestep_s": model.opt.timestep, "duration_s": duration},
        "applied_dynamics": applied_dynamics,
        "metrics_version": "2.0",
        "supervisor": {
            "id": "straight-path-v1" if path_hold else "none",
            "nominal_command": nominal_command.tolist() if policy_controller else None,
        },
        "controller": {
            "id": request.resources.controller.id,
            "mode": controller_mode or "legacy_hold_pose",
            "command": nominal_command.tolist() if policy_controller else None,
            "execution_provider": (
                policy_controller.execution_provider if policy_controller else None
            ),
        },
    }
    if recorder:
        reproduction["rendering"] = {
            "width": recorder.width,
            "height": recorder.height,
            "fps": recorder.fps,
            "frame_count": recorder.frame_count,
            "camera_mode": "follow_base_xy",
        }
    reproduction_path = output / "reproduction.json"
    reproduction_path.write_text(json.dumps(reproduction, indent=2, sort_keys=True))
    artifacts = [
        _artifact(job_id, state_path, "state_trajectory"),
        _artifact(job_id, action_path, "action_trajectory"),
        _artifact(job_id, contact_path, "contacts"),
        _artifact(job_id, reproduction_path, "reproduction_manifest"),
    ]
    include_video = recorder and (request.recording.video == "always" or events)
    if include_video:
        artifacts.extend(
            [
                _artifact(job_id, recorder.mp4_path, "rollout_video"),
                _artifact(job_id, recorder.gif_path, "rollout_preview"),
                _artifact(job_id, recorder.thumbnail_path, "rollout_thumbnail"),
            ]
        )
    elif recorder:
        for path in (recorder.mp4_path, recorder.gif_path, recorder.thumbnail_path):
            path.unlink(missing_ok=True)
    measured_metrics = locomotion_metrics.result() if locomotion_metrics else {}
    final_rpy = _quaternion_rpy(data.qpos[3:7])
    tracking_tolerance = float(request.task.parameters.get("velocity_rmse_tolerance", 0.35))
    linear_tolerance = float(
        request.task.parameters.get("linear_velocity_rmse_tolerance_mps", tracking_tolerance)
    )
    angular_tolerance = float(
        request.task.parameters.get("yaw_rate_rmse_tolerance_radps", tracking_tolerance)
    )
    command_tracking_success = bool(
        measured_metrics
        and termination_reason != "NUMERICAL_INSTABILITY"
        and measured_metrics["tracking_sample_count"] > 0
        and max(
            measured_metrics["forward_velocity_rmse_mps"],
            measured_metrics["lateral_velocity_rmse_mps"],
        )
        <= linear_tolerance
        and measured_metrics["yaw_rate_rmse_radps"] <= angular_tolerance
    )
    path_applicable = bool(
        policy_controller
        and abs(float(nominal_command[1])) < 1e-8
        and abs(float(nominal_command[2])) < 1e-8
    )
    path_success = bool(
        path_applicable
        and not fallen
        and termination_reason == "MAX_DURATION"
        and maximum_cross_track <= 0.2
        and maximum_heading_error <= 0.2
    )
    return RolloutResult(
        job_id=job_id,
        execution=ExecutionSummary(
            valid=termination_reason != "NUMERICAL_INSTABILITY",
            status=RemoteJobState.SUCCEEDED,
            termination_reason=termination_reason,
            determinism_level="BEST_EFFORT",
        ),
        task_facts={
            "standing_at_end": not fallen if termination_reason == "MAX_DURATION" else None,
            "fall_observed": fallen,
            "straight_path_applicable": path_applicable,
            "straight_path_success": path_success,
            "maximum_cross_track_m": maximum_cross_track,
            "maximum_heading_error_rad": maximum_heading_error,
            "cross_track_tolerance_m": 0.2,
            "heading_tolerance_rad": 0.2,
            "final_base_height_m": float(data.qpos[2]),
            "forward_distance_m": float(data.qpos[0] - initial_position[0]),
            "lateral_distance_m": float(data.qpos[1] - initial_position[1]),
            "final_roll_rad": final_rpy[0],
            "final_pitch_rad": final_rpy[1],
            "final_yaw_rad": final_rpy[2],
            "heading_change_rad": final_rpy[2] - initial_rpy[2],
            "walked_forward": (
                controller_mode == "walk"
                and not fallen
                and float(data.qpos[0] - initial_position[0])
                >= float(request.task.parameters.get("minimum_forward_distance_m", 0.2))
            ),
            "command_tracking_success": command_tracking_success,
            "velocity_rmse_tolerance": tracking_tolerance,
            "linear_velocity_rmse_tolerance_mps": linear_tolerance,
            "yaw_rate_rmse_tolerance_radps": angular_tolerance,
            **measured_metrics,
        },
        standard_events=events,
        summary_metrics={
            "simulation_steps": completed_steps,
            "contact_samples": sum(1 for _ in contact_path.open(encoding="utf-8")),
            "rendered_frames": recorder.frame_count if recorder else 0,
            **measured_metrics,
        },
        artifacts=artifacts,
        reproduction=reproduction,
    )


def run_probe(request: RolloutRequest, output: Path, groot_root: Path) -> RolloutResult:
    """Dependency-free backend used only by contract tests."""
    job_id = output.name
    reproduction = {
        "job_id": job_id,
        "runtime": {"backend": "probe"},
        "resolved_resources": request.resources.model_dump(mode="json"),
    }
    path = output / "reproduction.json"
    path.write_text(json.dumps(reproduction, sort_keys=True))
    return RolloutResult(
        job_id=job_id,
        execution=ExecutionSummary(
            valid=False,
            status=RemoteJobState.SUCCEEDED,
            termination_reason="PROBE_BACKEND_NO_SIMULATION",
        ),
        artifacts=[_artifact(job_id, path, "reproduction_manifest")],
        reproduction=reproduction,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--groot-root", type=Path, required=True)
    parser.add_argument("--backend", choices=("groot_mujoco", "probe"), required=True)
    parser.add_argument("--registry-root", type=Path)
    args = parser.parse_args()
    request = RolloutRequest.model_validate_json(args.request.read_text())
    if request.task.schema_id == "navigation@1.0" and args.backend == "groot_mujoco":
        from .navigation_worker import run_navigation

        if args.registry_root is None:
            raise ValueError("navigation requires registry root")
        result = run_navigation(request, args.output, args.groot_root, args.registry_root)
    else:
        result = (run_groot if args.backend == "groot_mujoco" else run_probe)(
            request, args.output, args.groot_root
        )
    (args.output / "execution_result.json").write_text(
        result.model_dump_json(by_alias=True, indent=2)
    )


if __name__ == "__main__":
    main()
