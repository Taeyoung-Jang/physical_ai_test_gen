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

from . import goal_policy as policy_module
from . import navigation_tools
from .api_transport import DiagnosticError
from .debug_log import Journal, exception_detail
from .policy import Geometry, Observation, PolicyError, validate_fresh
from .timing import RequestTiming


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)


def yaw(data):
    w, x, y, z = data.qpos[3:7]
    return float(math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z)))


def run(
    root,
    groot_root,
    policy,
    *,
    max_calls=10,
    max_seconds=120.0,
    enable_push=False,
    response_timeout=90.0,
):
    if not 1 <= max_calls <= 20 or not 3 <= max_seconds <= 120:
        raise ValueError("bounded call and simulation budgets required")
    timing = RequestTiming(response_timeout)
    config = Fixture()
    source = groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    xml = fixture.world_xml(config, source)
    (root / "scene.xml").write_text(xml)
    model = mujoco.MjModel.from_xml_string(xml)
    write(root / "robot_audit.json", audit.inspect(source, model))
    if enable_push:
        from clear_path.push_probe import ArmGaitController

        from . import push_execution
        from .push_policy import PushPolicy

        if not isinstance(policy, PushPolicy):
            raise ValueError("push-enabled execution requires matching capability policy")
        controller = ArmGaitController(groot_root, model)
    else:
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
    selected_geom = model.geom("clear_box_geom").id
    hands = push_execution.hand_geoms(model) if enable_push else set()
    active_push = None
    origin = "openai_api" if not isinstance(policy, policy_module.GoalMock) else "mock"
    write(
        root / "protocol.json",
        {
            "schema_version": "robot-goal-agent-push-v3"
            if enable_push
            else "robot-goal-agent-v2.1",
            "policy_origin": origin,
            "model": getattr(policy, "model", None),
            "prompt_version": "goal-agent-push-v3" if enable_push else policy_module.PROMPT_VERSION,
            "max_calls": max_calls,
            "max_simulation_s": max_seconds,
            "max_output_tokens_per_call": 4096,
            "response_deadline_wall_s": timing.deadline_s,
            "http_read_timeout_s": timing.read_s,
            "timing_contract": "goal-request-timing-v1; inference counts toward simulation budget",
            "debug_logging": "per-call api_call_NNN.jsonl; UTC and wall elapsed",
            "inference_wait": "robot-internal GT base/yaw hold; stale pose rejected",
            "observation": "RGB + full geometry + GT pose",
            "reference_path_provided": False,
            "robot_internal_planner": "BFS radius 0.40m; GPT chooses target",
            "manipulation_available": enable_push,
            "push_enabled": enable_push,
            "manipulation_scope": "short near-contact push only" if enable_push else "none",
            "initial_robot_xy_m": data.qpos[:2].tolist(),
            "controller_condition": "arm_ik_gait_push_v3" if enable_push else "original_gait",
            "scene_revision": fixture.identity(config),
            "execution_provider": controller.execution_provider,
            "source_hashes": {
                **(
                    {
                        name: audit.sha256(Path(__file__).with_name(name + ".py"))
                        for name in ("push_skill", "push_policy", "push_execution")
                    }
                    if enable_push
                    else {}
                ),
                **(
                    {
                        "arm_controller": audit.sha256(
                            Path(__file__).parents[1] / "clear_path/push_probe.py"
                        ),
                        "contact_control": audit.sha256(
                            Path(__file__).parents[1] / "clear_path/contact_control.py"
                        ),
                    }
                    if enable_push
                    else {}
                ),
                "timing": audit.sha256(Path(__file__).with_name("timing.py")),
                "debug_log": audit.sha256(Path(__file__).with_name("debug_log.py")),
                "api_transport": audit.sha256(Path(__file__).with_name("api_transport.py")),
                "wire_contract": audit.sha256(Path(__file__).with_name("wire_contract.py")),
                "runner": audit.sha256(Path(__file__)),
                "policy": audit.sha256(Path(policy_module.__file__)),
                "fixture": audit.sha256(Path(fixture.__file__)),
                "navigation_tools": audit.sha256(Path(navigation_tools.__file__)),
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
            (root / "contacts.jsonl").open("x") as contacts,
        ):

            def step(command):
                nonlocal next_frame, next_log, reason, failed, valid, reached_since
                if enable_push and active_push is None:
                    controller.upper_target += np.clip(
                        -controller.upper_target, -0.8 * dt, 0.8 * dt
                    )
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
                hand_contact, peak_force = False, 0.0
                for ci, c in enumerate(data.contact):
                    a, b = int(c.geom1), int(c.geom2)
                    if c.dist > 0 or ((a in world) == (b in world)):
                        continue
                    wg, rg = (a, b) if a in world else (b, a)
                    allowed = wg == floor and rg in foot
                    skill_contact = enable_push and push_execution.permitted(
                        active_push, rg, wg, hands, selected_geom
                    )
                    if skill_contact:
                        force = np.zeros(6)
                        mujoco.mj_contactForce(model, data, ci, force)
                        normal = abs(float(force[0]))
                        hand_contact, peak_force, allowed = True, max(peak_force, normal), True
                        if normal > 120:
                            reason, failed = "CONTACT_FORCE_LIMIT", True
                    if wg != floor:
                        contacts.write(
                            json.dumps(
                                {
                                    "time_s": float(data.time),
                                    "phase": phase,
                                    "robot_geom": rg,
                                    "world_geom": wg,
                                    "allowed": bool(allowed),
                                    "normal_force_n": normal if skill_contact else None,
                                }
                            )
                            + "\n"
                        )
                    if not allowed:
                        reason, failed = "FORBIDDEN_CONTACT", True
                if active_push is not None:
                    active_push.observe_contact(hand_contact, peak_force, dt)
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

            anchor, anchor_yaw = data.qpos[:3].copy(), yaw(data)
            while data.time < 2 and not failed:
                step(navigation_tools.hold_command(data.qpos[:3], yaw(data), anchor, anchor_yaw))
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
                anchor, anchor_yaw = data.qpos[:3].copy(), yaw(data)
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
                journal = Journal(
                    root / f"api_call_{calls:03}.jsonl",
                    obs.state_version,
                    read_timeout_s=timing.read_s,
                )
                future = executor.submit(journal.decide, policy, obs, png)
                calls += 1
                while not future.done() and not failed and data.time < max_seconds:
                    tick = time.monotonic()
                    step(
                        navigation_tools.hold_command(data.qpos[:3], yaw(data), anchor, anchor_yaw)
                    )
                    if time.monotonic() - began > timing.deadline_s:
                        diagnostic = {
                            "stage": "runner",
                            "limit_wall_s": timing.deadline_s,
                            "elapsed_wall_s": time.monotonic() - began,
                            "simulation_time_s": float(data.time),
                            "observation_version": obs.state_version,
                            "client_request_id": journal.client_request_id,
                        }
                        write(root / "runner_deadline.json", diagnostic)
                        raise DiagnosticError("response_deadline", diagnostic)
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
                    policy.feedback(action, {"status": "stale_rejected"})
                    record["execution"] = previous
                    decisions.write(json.dumps(record) + "\n")
                    continue
                accepted += 1
                record["execution"] = "accepted"
                decisions.write(json.dumps(record) + "\n")
                if action.action == "stop":
                    reason = "POLICY_STOP"
                    break
                if action.action == "push_object":
                    if not enable_push:
                        raise PolicyError("push_executor_disabled")
                    active_push, feedback = push_execution.prepare(
                        model, data, action, obs, max_seconds - float(data.time)
                    )
                    if active_push is not None:
                        began_push = float(data.time)
                        phase = "push_object"
                        while data.time - began_push < 18 and not failed:
                            goals, cmd = active_push.command(
                                float(data.time) - began_push,
                                data.qpos[:3].copy(),
                                yaw(data),
                                data.geom_xpos[selected_geom].copy(),
                                {
                                    side: data.site(f"{side}_push_site").xpos.copy()
                                    for side in ("left", "right")
                                },
                            )
                            if goals and controller.counter % 10 == 0:
                                controller.arm_targets(goals)
                            step(cmd)
                        feedback = active_push.result(
                            data.geom_xpos[selected_geom].tolist(),
                            valid=valid,
                            reason=reason if failed else "DURATION_REACHED",
                        )
                        if not failed and not active_push.control.released:
                            reason, failed = "SKILL_RELEASE_FAILURE", True
                        active_push = None
                        # Rate-limited neutral arms under gait/pose hold, no contact exemption.
                        phase = "push_handoff"
                        anchor, anchor_yaw = data.qpos[:3].copy(), yaw(data)
                        until = min(float(data.time) + 3, max_seconds)
                        while data.time < until and not failed:
                            step(
                                navigation_tools.hold_command(
                                    data.qpos[:3], yaw(data), anchor, anchor_yaw
                                )
                            )
                        if failed:
                            feedback.update(success=False, status="failed", reason=reason)
                        feedback["handoff_complete"] = not failed
                        feedback["actual_box_xyz_m"] = data.geom_xpos[selected_geom].tolist()
                    feedback["terminal_reason"] = reason if failed else None
                    feedback["actual_base_xyz_m"] = data.qpos[:3].tolist()
                    feedback["simulation_time_s"] = float(data.time)
                    write(root / f"skill_{obs.state_version:03}.json", feedback)
                    policy.feedback(action, feedback)
                    decisions.write(
                        json.dumps(
                            {
                                "event": "tool_result",
                                "observation_version": obs.state_version,
                                "result": feedback,
                            }
                        )
                        + "\n"
                    )
                    decisions.flush()
                    previous = "executed"
                    continue
                phase = action.action
                tool_result = {"status": "executed"}
                path = []
                if action.action in {"plan_path", "navigate_to"}:
                    current = obs.model_copy(update={"base_xyz_m": data.qpos[:3].tolist()})
                    tool_result = navigation_tools.plan(current, action.target_xy_m)
                    path = [point[:] for point in tool_result["path_xy_m"]]
                    write(root / f"tool_{obs.state_version:03}.json", tool_result)
                if action.action == "request_skill":
                    tool_result = {"status": "unsupported", "request": action.skill_request}
                anchor, anchor_yaw = data.qpos[:3].copy(), yaw(data)
                end = min(float(data.time) + action.duration_s, max_seconds)
                if action.action in {"plan_path", "request_skill"} or (
                    action.action == "navigate_to" and not path
                ):
                    end = min(float(data.time) + 0.2, max_seconds)
                while data.time < end and not failed:
                    if action.action == "move":
                        command = [action.vx_mps, action.vy_mps, action.yaw_rate_rps]
                    elif action.action == "navigate_to" and path:
                        if math.dist(data.qpos[:2], action.target_xy_m) < 0.12:
                            tool_result["status"] = "target_reached"
                            break
                        command = navigation_tools.follow_command(data.qpos[:3], yaw(data), path)
                    else:
                        command = navigation_tools.hold_command(
                            data.qpos[:3], yaw(data), anchor, anchor_yaw
                        )
                    step(command)
                if action.action == "navigate_to" and tool_result["status"] == "path_found":
                    tool_result["status"] = "execution_slice_ended"
                tool_result["actual_base_xyz_m"] = data.qpos[:3].tolist()
                tool_result["terminal_reason"] = reason if failed else None
                tool_result["simulation_time_s"] = float(data.time)
                policy.feedback(action, tool_result)
                decisions.write(
                    json.dumps(
                        {
                            "event": "tool_result",
                            "observation_version": obs.state_version,
                            "result": tool_result,
                        }
                    )
                    + "\n"
                )
                previous = "executed"
    except PolicyError as exc:
        reason, valid = str(exc), False
        error_diagnostic = getattr(exc, "diagnostic", {"code": reason, "stage": "runner"})
    except Exception as exc:
        write(root / "unexpected_error.json", {"exception_chain": exception_detail(exc)})
        raise
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
<a href='api_call_000.jsonl'>API call 0 debug log</a> ·
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
