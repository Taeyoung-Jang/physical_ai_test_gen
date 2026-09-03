from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
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
    for operation in request.interventions:
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
    try:
        with (
            state_path.open("w") as states,
            action_path.open("w") as actions,
            contact_path.open("w") as contacts,
        ):
            if recorder:
                recorder.capture(data, force=True)
            while data.time < duration:
                if policy_controller:
                    policy_controller.step()
                else:
                    q = data.qpos[7 : 7 + model.nu]
                    dq = data.qvel[6 : 6 + model.nu]
                    data.ctrl[:] = kp[: model.nu] * (target - q) - kd[: model.nu] * dq
                    mujoco.mj_step(model, data)
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
                actions.write(json.dumps({"time_s": data.time, "ctrl": data.ctrl.tolist()}) + "\n")
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
        "controller": {
            "id": request.resources.controller.id,
            "mode": controller_mode or "legacy_hold_pose",
            "command": policy_controller.command.tolist() if policy_controller else None,
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
    return RolloutResult(
        job_id=job_id,
        execution=ExecutionSummary(
            valid=True,
            status=RemoteJobState.SUCCEEDED,
            termination_reason="MAX_DURATION",
            determinism_level="BEST_EFFORT",
        ),
        task_facts={
            "standing_at_end": not fallen,
            "final_base_height_m": float(data.qpos[2]),
            "forward_distance_m": float(data.qpos[0] - initial_position[0]),
            "lateral_distance_m": float(data.qpos[1] - initial_position[1]),
            "walked_forward": (
                controller_mode == "walk"
                and not fallen
                and float(data.qpos[0] - initial_position[0])
                >= float(request.task.parameters.get("minimum_forward_distance_m", 0.2))
            ),
        },
        standard_events=events,
        summary_metrics={
            "simulation_steps": int(data.time / model.opt.timestep),
            "contact_samples": sum(1 for _ in contact_path.open(encoding="utf-8")),
            "rendered_frames": recorder.frame_count if recorder else 0,
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
    args = parser.parse_args()
    request = RolloutRequest.model_validate_json(args.request.read_text())
    result = (run_groot if args.backend == "groot_mujoco" else run_probe)(
        request, args.output, args.groot_root
    )
    (args.output / "execution_result.json").write_text(
        result.model_dump_json(by_alias=True, indent=2)
    )


if __name__ == "__main__":
    main()
