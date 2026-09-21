"""Isolated G1 camera-policy loop; no AFS, reference route or manipulation executor."""

import io
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import imageio.v2 as imageio
import mujoco
import numpy as np
from PIL import Image, ImageDraw

from clear_path import audit, fixture
from clear_path.contracts import Fixture
from simulation_server.groot_locomotion import G1OnnxController

from . import policy as policy_module
from .policy import Geometry, Observation, PolicyError, validate_fresh


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)


def yaw(data):
    w, x, y, z = data.qpos[3:7]
    return float(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def run(root, groot_root, policy, *, max_calls=10, max_seconds=30.0):
    if not 1 <= max_calls <= 20 or not 3 <= max_seconds <= 120:
        raise ValueError("bounded call and simulation budgets required")
    config = Fixture()
    source = groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    xml = fixture.world_xml(config, source)
    (root / "scene.xml").write_text(xml)
    model = mujoco.MjModel.from_xml_string(xml)
    write(root / "robot_audit.json", audit.inspect(source, model))
    controller = G1OnnxController(groot_root, "walk", np.zeros(3), model=model)
    if controller.execution_provider != "CUDAExecutionProvider":
        raise RuntimeError("CUDA required")
    controller.data = audit.initial_data(model, source)
    data = controller.data
    dt = model.opt.timestep
    world = {model.geom(n).id for n in [*fixture.WALLS, "clear_floor", "clear_box_geom"]}
    foot = {
        g for g in range(model.ngeom) if "ankle_roll" in model.body(int(model.geom_bodyid[g])).name
    }
    floor = model.geom("clear_floor").id
    origin = "openai_api" if isinstance(policy, policy_module.OpenAIPolicy) else "mock"
    write(
        root / "protocol.json",
        {
            "schema_version": "robot-vlm-loop-v1.1",
            "policy_origin": origin,
            "model": getattr(policy, "model", None),
            "prompt_version": policy_module.PROMPT_VERSION,
            "max_calls": max_calls,
            "max_simulation_s": max_seconds,
            "max_output_tokens_per_call": 2048,
            "response_deadline_wall_s": 30,
            "inference_wait": "physics continues with zero gait velocity; stale pose rejected",
            "observation": "RGB + full geometry + GT pose",
            "reference_path_provided": False,
            "manipulation_available": False,
            "scene_revision": fixture.identity(config),
            "execution_provider": controller.execution_provider,
            "source_hashes": {
                "api_transport": audit.sha256(Path(__file__).with_name("api_transport.py")),
                "wire_contract": audit.sha256(Path(__file__).with_name("wire_contract.py")),
                "runner": audit.sha256(Path(__file__)),
                "policy": audit.sha256(Path(policy_module.__file__)),
                "fixture": audit.sha256(Path(fixture.__file__)),
                "gait": audit.sha256(
                    Path(__file__).parents[1] / "simulation_server/groot_locomotion.py"
                ),
            },
            "self_collision_classification": "not_implemented",
        },
    )
    frames, calls, accepted = [], 0, 0
    reason, previous, phase = "BUDGET_EXHAUSTED", "none", "settle"
    failed, valid, reached_since = False, True, None
    next_frame, next_log = 0.0, 0.0
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 4.5, 120, -60
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    consumed = True
    video = None
    error_diagnostic = None
    try:
        with (
            mujoco.Renderer(model, height=540, width=960) as renderer,
            imageio.get_writer(root / "rollout.mp4", fps=12, macro_block_size=2) as video,
            (root / "states.jsonl").open("x") as states,
            (root / "decisions.jsonl").open("x") as decisions,
        ):

            def step(command):
                nonlocal next_frame, next_log, reason, failed, valid, reached_since
                controller.command[:] = command
                controller.step()
                mujoco.mj_forward(model, data)
                if (
                    not np.isfinite(data.qpos).all()
                    or not np.isfinite(data.qvel).all()
                    or not np.isfinite(data.ctrl).all()
                    or any(
                        data.warning[i].number
                        for i in (
                            mujoco.mjtWarning.mjWARN_BADQPOS,
                            mujoco.mjtWarning.mjWARN_BADQVEL,
                            mujoco.mjtWarning.mjWARN_BADQACC,
                        )
                    )
                ):
                    reason, failed, valid = "NUMERICAL_ERROR", True, False
                    return
                if np.any(data.xfrc_applied) or np.any(data.qfrc_applied):
                    reason, failed, valid = "EXTERNAL_FORCE_ERROR", True, False
                for c in data.contact:
                    a, b = int(c.geom1), int(c.geom2)
                    if c.dist > 0 or ((a in world) == (b in world)):
                        continue
                    wg, rg = (a, b) if a in world else (b, a)
                    if wg != floor or rg not in foot:
                        reason, failed = "FORBIDDEN_CONTACT", True
                if data.qpos[2] < 0.5 or data.body("pelvis").xmat.reshape(3, 3)[2, 2] < 0.7:
                    reason, failed = "FALL", True
                distance = np.linalg.norm(data.qpos[:2] - fixture.GOAL)
                reached_since = (
                    (float(data.time) if reached_since is None else reached_since)
                    if distance < 0.25
                    else None
                )
                if not failed and reached_since is not None and data.time - reached_since >= 1:
                    reason, failed = "GOAL_REACHED", True
                if data.time >= next_log:
                    states.write(
                        json.dumps(
                            {
                                "time_s": float(data.time),
                                "phase": phase,
                                "qpos": data.qpos.tolist(),
                                "qvel": data.qvel.tolist(),
                                "ctrl": data.ctrl.tolist(),
                                "command": controller.command.tolist(),
                            }
                        )
                        + "\n"
                    )
                    next_log += 0.05
                if data.time >= next_frame:
                    camera.lookat[:] = [data.qpos[0] + 0.4, data.qpos[1], 0.65]
                    renderer.update_scene(data, camera=camera)
                    frame = Image.fromarray(renderer.render())
                    draw = ImageDraw.Draw(frame)
                    draw.rectangle((0, 0, 960, 30), fill="#0f172a")
                    draw.text(
                        (10, 9), f"POLICY={origin} | t={data.time:.2f}s | {phase}", fill="white"
                    )
                    arr = np.asarray(frame).copy()
                    video.append_data(arr)
                    frames.append(arr)
                    next_frame += 1 / 12

            while data.time < 2 and not failed:
                step([0, 0, 0])
            while calls < max_calls and data.time < max_seconds and not failed:
                renderer.update_scene(data, camera="clear_robot_camera")
                buffer = io.BytesIO()
                Image.fromarray(renderer.render()).save(buffer, format="PNG")
                png = buffer.getvalue()
                cid = model.camera("clear_robot_camera").id
                obs = Observation(
                    state_version=calls,
                    simulation_time_s=float(data.time),
                    goal_xy_m=list(fixture.GOAL),
                    base_xyz_m=data.qpos[:3].tolist(),
                    yaw_rad=yaw(data),
                    previous_execution=previous,
                    camera_name="clear_robot_camera",
                    camera_fovy_deg=float(model.cam_fovy[cid]),
                    camera_xyz_m=data.cam_xpos[cid].tolist(),
                    camera_rotation_matrix=data.cam_xmat[cid].tolist(),
                    geometry=[
                        Geometry(
                            object_id=model.geom(g).name,
                            center_m=data.geom_xpos[g].tolist(),
                            size_m=(2 * model.geom_size[g]).tolist(),
                            rotation_matrix=data.geom_xmat[g].tolist(),
                        )
                        for g in sorted(world)
                    ],
                )
                write(root / f"observation_{calls:03}.json", obs.model_dump())
                (root / f"camera_{calls:03}.png").write_bytes(png)
                began = time.monotonic()
                phase = "inference_wait"
                decisions.write(
                    json.dumps(
                        {
                            "event": "call_started",
                            "observation_version": obs.state_version,
                            "origin": origin,
                        }
                    )
                    + "\n"
                )
                decisions.flush()
                consumed = False
                future = executor.submit(policy.decide, obs, png)
                calls += 1
                while not future.done() and not failed and data.time < max_seconds:
                    tick = time.monotonic()
                    step([0, 0, 0])
                    if time.monotonic() - began > 30:
                        raise PolicyError("response_deadline")
                    time.sleep(max(0, dt - (time.monotonic() - tick)))
                if failed or data.time >= max_seconds:
                    if not failed:
                        reason, valid = "INFERENCE_SIM_BUDGET", False
                    break
                try:
                    action, metadata = future.result()
                finally:
                    consumed = True
                record = {
                    "observation_version": obs.state_version,
                    "action": action.model_dump(),
                    "provider": metadata,
                    "latency_s": time.monotonic() - began,
                }
                try:
                    validate_fresh(action, obs, data.qpos[:3].tolist(), yaw(data))
                except ValueError:
                    previous = "stale_rejected"
                    record["execution"] = previous
                    decisions.write(json.dumps(record) + "\n")
                    continue
                accepted += 1
                record["execution"] = "accepted"
                decisions.write(json.dumps(record) + "\n")
                if action.action == "stop":
                    reason = "POLICY_STOP"
                    break
                phase = action.action
                end = min(float(data.time) + action.duration_s, max_seconds)
                while data.time < end and not failed:
                    step([action.vx_mps, action.vy_mps, action.yaw_rate_rps])
                previous = "executed"
    except PolicyError as exc:
        reason, valid = str(exc), False
        error_diagnostic = getattr(exc, "diagnostic", {"code": reason, "stage": "runner"})
    finally:
        if future is not None:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        if future is not None and not consumed:
            pending = {"executed": False, "observation_version": calls - 1}
            if future.cancelled():
                pending["status"] = "cancelled_before_start"
            else:
                try:
                    late_action, late_meta = future.result()
                    pending.update(
                        status="completed_after_termination",
                        provider=late_meta,
                        action=late_action.model_dump(),
                    )
                except PolicyError as exc:
                    pending.update(
                        status="failed_after_termination",
                        diagnostic=getattr(exc, "diagnostic", {"code": str(exc)}),
                    )
                except Exception as exc:
                    pending.update(status="internal_error", exception_type=type(exc).__name__)
            write(root / "pending_call.json", pending)
        # imageio's context manager skips close when unwinding an exception.
        # Explicit close waits for ffmpeg before result/manifest hashes are written.
        if video is not None:
            video.close()
        if error_diagnostic is not None:
            write(root / "failure_diagnostic.json", error_diagnostic)
        if np.isfinite(data.qpos).all() and np.isfinite(data.qvel).all():
            write(
                root / "terminal_state.json",
                {
                    "time_s": float(data.time),
                    "phase": phase,
                    "qpos": data.qpos.tolist(),
                    "qvel": data.qvel.tolist(),
                    "contacts": [
                        {
                            "geom1": int(c.geom1),
                            "geom2": int(c.geom2),
                            "body1": model.body(int(model.geom_bodyid[c.geom1])).name,
                            "body2": model.body(int(model.geom_bodyid[c.geom2])).name,
                            "distance_m": float(c.dist),
                        }
                        for c in data.contact
                        if c.dist <= 0
                    ],
                },
            )

    if frames:
        imageio.mimsave(root / "rollout.gif", frames, duration=1000 / 12, loop=0)
    result = {
        "valid_execution": valid,
        "success": reason == "GOAL_REACHED" and valid,
        "reason": reason,
        "error_diagnostic": error_diagnostic,
        "calls_attempted": calls,
        "api_calls_attempted": calls if origin == "openai_api" else 0,
        "policy_origin": origin,
        "duration_s": float(data.time),
        "goal_distance_m": float(np.linalg.norm(data.qpos[:2] - fixture.GOAL)),
        "live_actions_accepted": accepted if origin == "openai_api" else 0,
        "autonomous_task_success_validated": origin == "openai_api"
        and valid
        and reason == "GOAL_REACHED",
        "note": "Mock proves wiring only; task failure is not an infrastructure error",
    }
    write(root / "result.json", result)
    page = f"""<!doctype html><meta charset='utf-8'><h1>Robot policy: {origin}</h1>
<p>Result: {result["success"]}, reason: {reason}. Mock is NOT VLM evidence.</p>
<video controls width='960' src='rollout.mp4'></video><p><a href='rollout.gif'>GIF</a></p>
<p><a href='camera_000.png'>Robot camera input</a> ·
<a href='decisions.jsonl'>Decisions</a> · <a href='protocol.json'>Protocol</a></p>"""
    (root / "report.html").write_text(page)
    write(
        root / "manifest.json",
        {
            "artifacts": [
                {"path": p.name, "sha256": audit.sha256(p)}
                for p in sorted(root.iterdir())
                if p.is_file()
            ]
        },
    )
    return result
