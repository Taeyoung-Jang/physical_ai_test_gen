"""Isolated goal-driven G1 loop. AFS controls scenes, never robot decisions."""

import io
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from html import escape
from importlib.metadata import version
from pathlib import Path

import imageio.v2 as imageio
import mujoco
import numpy as np
from PIL import Image, ImageDraw

from clear_path import audit, fixture
from simulation_server.groot_locomotion import G1OnnxController

from . import goal_policy as policy_module
from . import navigation_tools
from .api_transport import DiagnosticError
from .behavior_events import BehaviorEvents
from .budget import simulation_limit
from .debug_log import Journal, exception_detail
from .policy import Geometry, Observation, PolicyError, validate_fresh
from .scene_config import validate_scene
from .task_outcome import GoalEvaluator, digest, task_contract
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
    max_seconds=None,
    enable_push=False,
    response_timeout=90.0,
    scene_config=None,
    evaluation_profile="goal_outcome_v1",
):
    if not 1 <= max_calls <= 20:
        raise ValueError("bounded call budget 1..20 required")
    requested_max_seconds = max_seconds
    contract = task_contract(fixture.GOAL, max_calls, max_seconds, evaluation_profile)
    evaluator = GoalEvaluator(contract)
    guarded = evaluation_profile == "legacy_guarded"
    policy.task_contract = contract
    max_seconds = simulation_limit(max_seconds)
    timing = RequestTiming(response_timeout)
    config = validate_scene(scene_config)
    source = groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    xml = fixture.world_xml(config, source)
    (root / "scene.xml").write_text(xml)
    model = mujoco.MjModel.from_xml_string(xml)
    robot_audit = audit.inspect(source, model)
    write(root / "robot_audit.json", robot_audit)
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
    world = {model.geom(n).id for n in fixture.world_geom_names(config)}
    # Evaluation artifacts only; no reference path is supplied to the policy.
    write(root / "scene_graph.json", fixture.graph(config))
    write(root / "navigation_map.json", fixture.navigation_map(config))
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
            "schema_version": "robot-goal-agent-v5",
            "evaluation_profile": evaluation_profile,
            "task_contract": contract,
            "task_contract_sha256": digest(contract),
            "policy_origin": origin,
            "model": getattr(policy, "model", None),
            "prompt_version": "goal-agent-push-v5" if enable_push else policy_module.PROMPT_VERSION,
            "max_calls": max_calls,
            "max_simulation_s": requested_max_seconds,
            "simulation_time_unlimited": requested_max_seconds is None,
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
            "controller_condition": "arm_ik_gait_push_align_v4" if enable_push else "original_gait",
            "scene_revision": fixture.identity(config),
            "scene_config": config.model_dump(),
            "execution_provider": controller.execution_provider,
            "physics_timestep_s": float(dt),
            "runtime_versions": {
                name: version(name) for name in ("mujoco", "numpy", "onnxruntime-gpu")
            },
            "robot_resources": {
                str(Path(path).relative_to(groot_root)): value
                for path, value in robot_audit.get("source_sha256", {}).items()
            },
            "source_hashes": {
                "scene_config": audit.sha256(Path(__file__).with_name("scene_config.py")),
                "fixture_contracts": audit.sha256(
                    Path(__file__).parents[1] / "clear_path/contracts.py"
                ),
                **(
                    {
                        name: audit.sha256(Path(__file__).with_name(name + ".py"))
                        for name in (
                            "push_skill",
                            "push_policy",
                            "push_execution",
                            "push_alignment",
                        )
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
                "budget": audit.sha256(Path(__file__).with_name("budget.py")),
                "task_outcome": audit.sha256(Path(__file__).with_name("task_outcome.py")),
                "behavior_events": audit.sha256(Path(__file__).with_name("behavior_events.py")),
                "timing": audit.sha256(Path(__file__).with_name("timing.py")),
                "debug_log": audit.sha256(Path(__file__).with_name("debug_log.py")),
                "api_transport": audit.sha256(Path(__file__).with_name("api_transport.py")),
                "wire_contract": audit.sha256(Path(__file__).with_name("wire_contract.py")),
                "runner": audit.sha256(Path(__file__)),
                "policy": audit.sha256(Path(policy_module.__file__)),
                "observation_contract": audit.sha256(Path(__file__).with_name("policy.py")),
                "robot_audit": audit.sha256(Path(audit.__file__)),
                "fixture": audit.sha256(Path(fixture.__file__)),
                "navigation_tools": audit.sha256(Path(navigation_tools.__file__)),
                "gait": audit.sha256(
                    Path(__file__).parents[1] / "simulation_server/groot_locomotion.py"
                ),
            },
            "self_collision_classification": "not_implemented",
            "recording": {
                "video": "rollout.mp4",
                "video_fps": 12,
                "gif_enabled": False,
                "retain_frame_history": False,
            },
        },
    )
    protocol = json.loads((root / "protocol.json").read_text())
    condition_sha256 = digest(
        {k: v for k, v in protocol.items() if k not in {"scene_revision", "scene_config"}}
    )
    calls, accepted = 0, 0
    # GIF disabled: retaining full-resolution frames grows RAM with episode duration.
    # frames = []
    reason, previous, phase = "BUDGET_EXHAUSTED", "none", "settle"
    terminated, valid = False, True
    next_frame, next_log = 0.0, 0.0
    camera = mujoco.MjvCamera()
    camera.distance, camera.azimuth, camera.elevation = 4.5, 120, -60
    executor = ThreadPoolExecutor(max_workers=1)
    future = None
    consumed = True
    video = None
    error_diagnostic = None
    observer = None
    try:
        with (
            mujoco.Renderer(model, height=540, width=960) as renderer,
            imageio.get_writer(root / "rollout.mp4", fps=12, macro_block_size=2) as video,
            (root / "states.jsonl").open("x") as states,
            (root / "decisions.jsonl").open("x") as decisions,
            (root / "contacts.jsonl").open("x") as contacts,
            (root / "events.jsonl").open("x") as events,
        ):
            observer = BehaviorEvents(events)

            def step(command):
                nonlocal next_frame, next_log, reason, terminated, valid
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
                    reason, terminated, valid = "NUMERICAL_ERROR", True, False
                    return
                if np.any(data.xfrc_applied) or np.any(data.qfrc_applied):
                    reason, terminated, valid = "EXTERNAL_FORCE_ERROR", True, False
                    return
                hand_contact, peak_force = False, 0.0
                conditions = {}
                for ci, c in enumerate(data.contact):
                    a, b = int(c.geom1), int(c.geom2)
                    if c.dist > 0 or ((a in world) == (b in world)):
                        continue
                    wg, rg = (a, b) if a in world else (b, a)
                    allowed = wg == floor and rg in foot
                    skill_contact = enable_push and push_execution.permitted(
                        active_push, rg, wg, hands, selected_geom
                    )
                    force = np.zeros(6)
                    mujoco.mj_contactForce(model, data, ci, force)
                    normal = abs(float(force[0]))
                    if not np.isfinite(force).all():
                        reason, terminated, valid = "NUMERICAL_ERROR", True, False
                        return
                    if skill_contact:
                        hand_contact, peak_force, allowed = True, max(peak_force, normal), True
                        if guarded and normal > 120:
                            reason, terminated = "CONTACT_FORCE_LIMIT", True
                    contact = {
                        "time_s": float(data.time),
                        "phase": phase,
                        "robot_geom": rg,
                        "world_geom": wg,
                        "robot_geom_name": model.geom(rg).name,
                        "world_geom_name": model.geom(wg).name,
                        "robot_body": model.body(int(model.geom_bodyid[rg])).name,
                        "world_body": model.body(int(model.geom_bodyid[wg])).name,
                        "legacy_allowed": bool(allowed),
                        "normal_force_n": normal,
                        "distance_m": float(c.dist),
                        "effective_friction": c.friction.tolist(),
                    }
                    contacts.write(json.dumps(contact) + "\n")
                    key = (rg, wg, phase)
                    pair = conditions.setdefault(
                        key,
                        {
                            "kind": "contact",
                            "robot_geom": rg,
                            "world_geom": wg,
                            "robot_body": contact["robot_body"],
                            "world_geom_name": contact["world_geom_name"],
                            "legacy_allowed": bool(allowed),
                            "peak_normal_force_n": 0.0,
                            "sum_normal_force_n": 0.0,
                        },
                    )
                    pair["peak_normal_force_n"] = max(pair["peak_normal_force_n"], normal)
                    pair["sum_normal_force_n"] += normal
                    if guarded and not allowed:
                        reason, terminated = "FORBIDDEN_CONTACT", True
                if active_push is not None:
                    active_push.observe_contact(hand_contact, peak_force, dt)
                if data.qpos[2] < 0.5 or data.body("pelvis").xmat.reshape(3, 3)[2, 2] < 0.7:
                    conditions["fall"] = {"kind": "fall", "base_height_m": float(data.qpos[2])}
                    if guarded:
                        reason, terminated = "FALL", True
                observer.update(conditions, float(data.time), phase, dt)
                # Only predeclared goal conditions determine success; no upright/contact clause.
                if (
                    not terminated
                    and data.time <= max_seconds + 1e-9
                    and evaluator.observe(float(data.time), data.qpos[:2])
                ):
                    reason, terminated = "GOAL_REACHED", True
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
                                "goal_distance_m": float(
                                    np.linalg.norm(data.qpos[:2] - fixture.GOAL)
                                ),
                                "goal_dwell_s": 0.0
                                if evaluator.reached_since is None
                                else float(data.time) - evaluator.reached_since,
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
                    # frames.append(arr)  # GIF disabled; MP4 is streamed to disk.
                    next_frame += 1 / 12

            anchor, anchor_yaw = data.qpos[:3].copy(), yaw(data)
            while data.time < 2 and not terminated:
                step(navigation_tools.hold_command(data.qpos[:3], yaw(data), anchor, anchor_yaw))
            while calls < max_calls and data.time < max_seconds and not terminated:
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
                    behavior_feedback=observer.observation(),
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
                while not future.done() and not terminated and data.time < max_seconds:
                    tick = time.monotonic()
                    step(
                        navigation_tools.hold_command(data.qpos[:3], yaw(data), anchor, anchor_yaw)
                    )
                    if (
                        not terminated
                        and data.time < max_seconds
                        and time.monotonic() - began > timing.deadline_s
                    ):
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
                if terminated or data.time >= max_seconds:
                    if not terminated:
                        reason = "INFERENCE_SIM_BUDGET"
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
                    alignment = {"attempted": False, "status": "not_needed"}
                    initial_readiness = push_execution.measure(model, data, action)
                    if feedback and feedback["reason"] in {
                        "near_aligned_approach_required",
                        "approach_heading_required",
                    }:
                        phase = "push_alignment"
                        with (root / f"alignment_{obs.state_version:03}.jsonl").open("x") as trace:

                            def record_alignment(row):
                                trace.write(json.dumps(row) + "\n")
                                trace.flush()

                            active_push, feedback, alignment = push_execution.align(
                                model,
                                data,
                                action,
                                obs,
                                max_seconds,
                                step,
                                lambda: terminated,
                                record_alignment,
                            )
                        if terminated and reason == "GOAL_REACHED" and feedback is not None:
                            feedback.update(status="interrupted_by_goal", reason=reason)
                    if active_push is not None:
                        began_push = float(data.time)
                        phase = "push_object"
                        while (
                            data.time - began_push < 18
                            and data.time < max_seconds
                            and not terminated
                        ):
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
                        if not valid:
                            active_push = None
                            break
                        feedback = active_push.result(
                            data.geom_xpos[selected_geom].tolist(),
                            valid=valid,
                            reason=reason if terminated else "DURATION_REACHED",
                        )
                        if terminated and reason == "GOAL_REACHED":
                            feedback.update(status="interrupted_by_goal", reason=reason)
                        if not terminated and not active_push.control.released:
                            feedback.update(
                                success=False, status="failed", reason="SKILL_RELEASE_FAILURE"
                            )
                            if guarded:
                                reason, terminated = "SKILL_RELEASE_FAILURE", True
                        active_push = None
                        # Existing robot handoff continues; contact is an observation in goal mode.
                        phase = "push_handoff"
                        anchor, anchor_yaw = data.qpos[:3].copy(), yaw(data)
                        handoff_deadline = float(data.time) + 3
                        until = min(handoff_deadline, max_seconds)
                        while data.time < until and not terminated:
                            step(
                                navigation_tools.hold_command(
                                    data.qpos[:3], yaw(data), anchor, anchor_yaw
                                )
                            )
                        if terminated and reason != "GOAL_REACHED":
                            feedback.update(success=False, status="failed", reason=reason)
                        feedback["handoff_complete"] = (
                            not terminated and data.time + 1e-9 >= handoff_deadline
                        )
                        feedback["actual_box_xyz_m"] = data.geom_xpos[selected_geom].tolist()
                    feedback["alignment"] = alignment
                    if not valid:
                        break
                    feedback["readiness_before"] = initial_readiness
                    feedback["readiness_after"] = push_execution.measure(model, data, action)
                    feedback["terminal_reason"] = reason if terminated else None
                    feedback["actual_base_xyz_m"] = data.qpos[:3].tolist()
                    feedback["simulation_time_s"] = float(data.time)
                    if not feedback.get("success", False):
                        observer.emit(
                            "skill_interrupted"
                            if feedback.get("status") == "interrupted_by_goal"
                            else "skill_failure",
                            float(data.time),
                            phase,
                            reason=feedback.get("reason"),
                            skill="push_object",
                        )
                    feedback["behavior_feedback"] = observer.observation()
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
                while data.time < end and not terminated:
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
                if not valid:
                    break
                if action.action == "navigate_to" and tool_result["status"] == "path_found":
                    tool_result["status"] = "execution_slice_ended"
                tool_result["actual_base_xyz_m"] = data.qpos[:3].tolist()
                tool_result["terminal_reason"] = reason if terminated else None
                tool_result["simulation_time_s"] = float(data.time)
                tool_result["behavior_feedback"] = observer.observation()
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
            if not terminated and data.time >= max_seconds and reason != "INFERENCE_SIM_BUDGET":
                reason = "SIMULATION_BUDGET"
            observer.close(float(data.time), phase)
    except PolicyError as exc:
        reason, valid = str(exc), False
        error_diagnostic = getattr(exc, "diagnostic", {"code": reason, "stage": "runner"})
    except Exception as exc:
        write(root / "unexpected_error.json", {"exception_chain": exception_detail(exc)})
        reason, valid = "UNEXPECTED_ERROR", False
        error_diagnostic = {"code": reason, "exception_chain": exception_detail(exc)}
    except KeyboardInterrupt:
        reason, valid = "CANCELLED", False
    finally:
        if observer is not None and observer.active:
            # Exception paths leave the with-block first; preserve truncated episode endpoints.
            with (root / "events.jsonl").open("a") as stream:
                observer.stream = stream
                observer.close(float(data.time), phase)
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

    # GIF disabled by request; do not buffer frames or delay result saving for conversion.
    # if frames:
    #     imageio.mimsave(root / "rollout.gif", frames, duration=1000 / 12, loop=0)
    result = {
        **evaluator.result(reason, valid),
        "robot_condition_sha256": condition_sha256,
        "scene_revision": fixture.identity(config),
        "events_summary": observer.summary() if observer is not None else {},
        "reason": reason,
        "error_diagnostic": error_diagnostic,
        "calls_attempted": calls,
        "api_calls_attempted": calls if origin == "openai_api" else 0,
        "policy_origin": origin,
        "duration_s": float(data.time),
        "goal_distance_m": float(np.linalg.norm(data.qpos[:2] - fixture.GOAL))
        if np.isfinite(data.qpos[:2]).all()
        else None,
        "live_actions_accepted": accepted if origin == "openai_api" else 0,
        "autonomous_task_success_validated": origin == "openai_api"
        and valid
        and reason == "GOAL_REACHED",
        "note": "Mock proves wiring only; not VLM evidence"
        if origin == "mock"
        else "Goal outcome under the recorded robot, task and budget; events are not task verdicts",
    }
    write(root / "result.json", result)
    page = f"""<!doctype html><meta charset='utf-8'><h1>Robot policy: {origin}</h1>
<p>Task outcome: {result["task_outcome"]}; profile: {evaluation_profile}; reason: {reason}.</p>
<p>{result["note"]}</p>
<p>Goal distance: {result["goal_distance_m"]} m; calls: {calls}/{max_calls}.</p>
<details><summary>Behavior events (not task verdicts)</summary>
<pre>{escape(json.dumps(result["events_summary"], indent=2))}</pre></details>
<video controls width='960' src='rollout.mp4'></video><p>MP4 recording only; GIF disabled.</p>
<p><a href='camera_000.png'>Robot camera input</a> ·
<a href='api_call_000.jsonl'>API call 0 debug log</a> ·
<a href='decisions.jsonl'>Decisions</a> · <a href='events.jsonl'>Behavior events</a> ·
<a href='result.json'>Goal outcome</a> · <a href='protocol.json'>Protocol</a></p>"""
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
