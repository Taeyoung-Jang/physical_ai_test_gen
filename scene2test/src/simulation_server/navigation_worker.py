"""Procedural-world G1 navigation rollout with bounded execution and evidence."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

from failure_client.contracts import ExecutionSummary, RolloutResult, StandardEvent


def run_navigation(request, output: Path, groot_root: Path, registry_root: Path):
    os.environ.setdefault("MUJOCO_GL", "egl")
    import mujoco
    import numpy as np

    from procedural_world.core import navigation_map, scene_graph

    from .groot_locomotion import G1OnnxController
    from .navigation import VERSION, Follower
    from .registry import ManifestRegistry
    from .worker import LocomotionMetrics, RolloutRecorder, _artifact, _quaternion_rpy
    from .worlds import compose_model, resolve_world

    spec = resolve_world(ManifestRegistry(registry_root), request.resources.scene)
    nav = navigation_map(spec)
    model, source_hashes = compose_model(spec, groot_root, output)
    for resource, filename in (
        (request.resources.robot, "g1_gear_wbc.xml"),
        (request.resources.controller, "policy/GR00T-WholeBodyControl-Walk.onnx"),
        (request.resources.policy, "policy/GR00T-WholeBodyControl-Walk.onnx"),
    ):
        digest = source_hashes["decoupled_wbc/sim2mujoco/resources/robots/g1/" + filename]
        if resource.revision != "sha256:" + digest:
            raise ValueError("actual robot/policy bytes differ from requested revision")
    controller = G1OnnxController(groot_root, "walk", np.zeros(3), model=model)
    data = controller.data
    model.opt.timestep = request.execution.physics_timestep_s or 0.005
    params = request.task.parameters
    follower = Follower(
        nav, params.get("speed_mps", 0.3), params.get("goal_tolerance_m", 0.25), boxes=spec.boxes
    )
    heading = math.atan2(*(follower.path[1] - follower.path[0])[::-1])
    data.qpos[:2] = spec.spawn_xy
    data.qpos[3:7] = [math.cos(heading / 2), 0, 0, math.sin(heading / 2)]
    mujoco.mj_forward(model, data)
    for name, value in (
        ("scene_spec.json", spec.to_dict()),
        ("scene_graph.json", scene_graph(spec).to_dict()),
        ("navigation_map.json", nav),
        ("navigation_path.json", follower.path.tolist()),
    ):
        (output / name).write_text(json.dumps(value, indent=2))

    recorder = (
        RolloutRecorder(model, output, request.execution.maximum_duration_s)
        if request.recording.video != "never"
        else None
    )
    if recorder:
        recorder.camera.elevation = -65
        recorder.camera.distance = 5.5
    metrics = LocomotionMetrics(np.zeros(3), model.opt.timestep)
    events, trajectory = [], []
    wall_ids = {model.geom("world_" + b.id).id for b in spec.boxes}
    world_ids = wall_ids | {model.geom("world_floor").id}
    robot_ids = set(range(model.ngeom)) - world_ids
    reason, collision, fallen = "MAX_DURATION", False, False
    settle = (
        request.execution.settling_duration_s
        if request.execution.settling_duration_s is not None
        else 1.0
    )
    last_motion_xy, last_motion_time = data.qpos[:2].copy(), settle
    reached_since = None
    steps = 0
    next_log = 0.0
    trajectory_path = output / "state_trajectory.jsonl"
    action_path = output / "action_trajectory.jsonl"
    contact_path = output / "contacts.jsonl"
    try:
        with (
            trajectory_path.open("w") as states,
            action_path.open("w") as actions,
            contact_path.open("w") as contacts,
        ):
            if recorder:
                recorder.capture(data, force=True)
            for _ in range(math.ceil(request.execution.maximum_duration_s / model.opt.timestep)):
                before = float(data.time)
                yaw = _quaternion_rpy(data.qpos[3:7])[2]
                controller.command = (
                    np.zeros(3) if before < settle else follower.command(data.qpos[:2], yaw)
                )
                controller.step()
                steps += 1
                if (
                    not np.all(np.isfinite(data.qpos))
                    or not np.all(np.isfinite(data.qvel))
                    or data.time <= before
                ):
                    reason = "NUMERICAL_INSTABILITY"
                    break
                mujoco.mj_forward(model, data)
                metrics.command = controller.command.copy()
                metrics.update(model, data)
                if data.time >= next_log:
                    record = {
                        "time_s": float(data.time),
                        "qpos": data.qpos.tolist(),
                        "qvel": data.qvel.tolist(),
                        "waypoint_index": follower.index,
                    }
                    states.write(json.dumps(record) + "\n")
                    actions.write(
                        json.dumps(
                            {
                                "time_s": float(data.time),
                                "command": controller.command.tolist(),
                                "ctrl": data.ctrl.tolist(),
                            }
                        )
                        + "\n"
                    )
                    trajectory.append([float(data.time), *data.qpos[:2].tolist()])
                    next_log += 0.05
                for c in data.contact:
                    if c.dist <= 0 and (
                        (c.geom1 in wall_ids and c.geom2 in robot_ids)
                        or (c.geom2 in wall_ids and c.geom1 in robot_ids)
                    ):
                        collision = True
                        contacts.write(
                            json.dumps(
                                {
                                    "time_s": float(data.time),
                                    "geom1": mujoco.mj_id2name(
                                        model, mujoco.mjtObj.mjOBJ_GEOM, c.geom1
                                    ),
                                    "geom2": mujoco.mj_id2name(
                                        model, mujoco.mjtObj.mjOBJ_GEOM, c.geom2
                                    ),
                                    "position_m": c.pos.tolist(),
                                    "distance_m": float(c.dist),
                                }
                            )
                            + "\n"
                        )
                roll, pitch, _ = _quaternion_rpy(data.qpos[3:7])
                fallen = data.qpos[2] < 0.45 or max(abs(roll), abs(pitch)) > 1.0
                goal_distance = np.linalg.norm(data.qpos[:2] - spec.goal_xy)
                if goal_distance <= follower.tolerance:
                    reached_since = float(data.time) if reached_since is None else reached_since
                else:
                    reached_since = None
                if np.linalg.norm(data.qpos[:2] - last_motion_xy) > 0.1:
                    last_motion_xy, last_motion_time = data.qpos[:2].copy(), float(data.time)
                if recorder:
                    recorder.capture(data)
                if fallen:
                    reason = "FALL"
                elif collision:
                    reason = "COLLISION"
                elif reached_since is not None and data.time - reached_since >= 1.0:
                    reason = "GOAL_REACHED"
                elif data.time - last_motion_time > params.get("stuck_timeout_s", 20.0):
                    reason = "STUCK"
                if reason != "MAX_DURATION":
                    break
    finally:
        if recorder:
            recorder.close()
    valid = reason != "NUMERICAL_INSTABILITY"
    success = valid and reason == "GOAL_REACHED" and not collision and not fallen
    events.append(StandardEvent(event_type=reason, timestamp_s=max(0.0, float(data.time))))
    facts = {
        "navigation_success": success,
        "goal_reached": reason == "GOAL_REACHED",
        "collision_observed": collision,
        "fall_observed": bool(fallen),
        "stuck": reason == "STUCK",
        "standing_at_end": not bool(fallen) if valid else None,
        "goal_distance_m": float(np.linalg.norm(data.qpos[:2] - spec.goal_xy)),
        "goal_tolerance_m": follower.tolerance,
        "elapsed_simulation_s": float(data.time),
        "reference_path_length_m": nav["path_length_m"],
        "waypoints_reached": follower.index - 1,
        "waypoints_total": len(follower.path) - 1,
        "actual_path_length_m": sum(
            math.dist(a[1:], b[1:]) for a, b in zip(trajectory, trajectory[1:])
        ),
        **metrics.result(),
    }
    reproduction = {
        "resolved_resources": request.resources.model_dump(mode="json"),
        "scene_revision": spec.revision,
        "source_resource_sha256": source_hashes,
        "runtime": {
            "backend": "groot_mujoco",
            "mujoco_version": mujoco.__version__,
            "execution_provider": controller.execution_provider,
        },
        "navigator": {
            "id": VERSION,
            "parameters": params,
            "observation": "ground_truth_pose_and_map",
            "footprint_radius_m": spec.config.robot_radius_m,
            "safety_margin_m": spec.config.safety_margin_m,
        },
        "execution": {
            "seed": request.execution.seed,
            "timestep_s": model.opt.timestep,
            "settling_s": settle,
            "maximum_duration_s": request.execution.maximum_duration_s,
        },
        "code_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [
                Path(__file__),
                Path(__file__).with_name("navigation.py"),
                Path(__file__).with_name("worlds.py"),
                Path(__file__).with_name("groot_locomotion.py"),
            ]
        },
        "rendering": {
            "frame_count": recorder.frame_count,
            "fps": recorder.fps,
            "camera_mode": "overhead_follow_base_xy",
        }
        if recorder
        else None,
        "metrics_version": "navigation-1.0",
        "task_facts": facts,
    }
    (output / "reproduction.json").write_text(json.dumps(reproduction, indent=2))
    _plot(spec, nav, trajectory, output / "trajectory.png")
    filenames = {
        "state_trajectory.jsonl": "state_trajectory",
        "action_trajectory.jsonl": "action_trajectory",
        "contacts.jsonl": "contacts",
        "reproduction.json": "reproduction_manifest",
        "scene_spec.json": "scene_spec",
        "scene_graph.json": "scene_graph",
        "navigation_map.json": "navigation_map",
        "navigation_path.json": "navigation_path",
        "composed_scene.xml": "execution_scene",
        "trajectory.png": "navigation_trajectory",
    }
    if recorder:
        filenames.update(
            {
                "rollout.mp4": "rollout_video",
                "rollout.gif": "rollout_preview",
                "thumbnail.png": "rollout_thumbnail",
            }
        )
    return RolloutResult(
        job_id=output.name,
        execution=ExecutionSummary(
            valid=valid,
            status="SUCCEEDED",
            termination_reason=reason,
            determinism_level="BEST_EFFORT",
        ),
        task_facts=facts,
        standard_events=events,
        summary_metrics={"simulation_steps": steps},
        artifacts=[_artifact(output.name, output / name, kind) for name, kind in filenames.items()],
        reproduction=reproduction,
    )


def _plot(spec, nav, trajectory, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(8, 8))
    ax.imshow(
        np.array(nav["blocked"]),
        origin="lower",
        cmap="Greys",
        vmin=0,
        vmax=1,
        extent=[
            0,
            spec.config.width * spec.config.cell_size_m,
            0,
            spec.config.height * spec.config.cell_size_m,
        ],
    )
    reference = np.array(nav["path_xy_m"])
    ax.plot(reference[:, 0], reference[:, 1], "--", label="Reference footprint-safe path")
    if trajectory:
        actual = np.array(trajectory)
        ax.plot(actual[:, 1], actual[:, 2], label="Actual G1 base trajectory")
    ax.scatter(*spec.spawn_xy, c="green", label="Spawn")
    ax.scatter(*spec.goal_xy, c="red", label="Goal")
    ax.set(xlabel="World X (m)", ylabel="World Y (m)", title=spec.scene_id, aspect="equal")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
