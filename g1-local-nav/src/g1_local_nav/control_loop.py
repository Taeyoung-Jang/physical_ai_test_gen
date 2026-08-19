"""Core closed-loop algorithm (blueprint §12): sense -> decide -> act -> stop, chunked.

VLM inference does not run concurrently with movement — the robot STOPs before every camera
read and every decision, and only moves for a fixed action_duration_s before stopping again.
This is deliberate (blueprint §5.2): holding the previous command while waiting on a slow VLM
call would let the robot keep walking on stale intent, causing overshoot.
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Protocol

from .action import NavAction
from .action_mapper import ActionMapper
from .config import AppConfig
from .episode import EpisodeResult
from .metrics import StepRecord, compute_metrics
from .recorder import Recorder
from .robot_runtime import GRASP_REACH_POSE, GRASP_REST_POSE, G1Runtime, RobotFrame
from .safety import Watchdog, check_command_safety, check_frame_safety
from .vlm_client import VlmClient

# print(..., flush=True), not logging — under mjpython, plain logging.getLogger(...).info/
# warning() calls were never visible in the terminal across many live runs (see conversation
# record: [diag] logging.info() lines added for a live debugging session never appeared in the
# user's terminal output at all, while print() output from third-party code in the same process
# always did). Root cause not fully diagnosed (likely something about how mjpython's Python
# runtime handles the logging module's default StreamHandler/stdout under macOS's app bundle
# launch), but print(flush=True) reliably works, so every runtime message in this module uses
# that instead now.

# Matches the value scripts/run_pickup_smoke.py used for its first live end-to-end success
# (grasp distance ~0.47m against this 0.5m radius, see conversation record) — not re-derived
# here, deliberately kept identical so the closed loop's GRASP behaves the same as what was
# already proven live.
GRASP_MAX_DISTANCE_M = 0.5


def _target_distance_m(frame: RobotFrame, config: AppConfig) -> float | None:
    """Ground-truth XY distance to the red-box target (blueprint §14.3). None whenever
    frame.base_x/base_y aren't available — e.g. FakeG1Runtime in tests, or anything other than
    the real MuJoCo sim."""
    if frame.base_x is None or frame.base_y is None:
        return None
    return math.hypot(frame.base_x - config.task.target_x, frame.base_y - config.task.target_y)


async def _ramp_arm(
    runtime: G1Runtime, from_pose: dict, to_pose: dict, steps: int = 10, step_dt: float = 0.05, settle_s: float = 0.5
) -> None:
    """Async twin of scripts/run_pickup_smoke.py's ramp_arm() — moves the arm through
    intermediate waypoints instead of jumping straight to `to_pose`. A one-shot jump is what
    knocked the pickup target off its pedestal on an early live run (see conversation record);
    ramping fixed it there, so control_loop.py uses the same technique rather than something
    untested. Uses asyncio.sleep, not time.sleep, since this runs inside run_episode()'s async
    loop alongside the watchdog task — a blocking sleep here would stall the watchdog too.

    The trailing settle_s hold at `to_pose` (not part of the original ramp) was missing here
    until a live diagnostic caught it: joints are PD-controlled, not teleported, so they need
    real time to converge onto a newly-commanded target. Without any hold after the last ramp
    step, [diag] logging showed the wrist only partway between REST and REACH in both
    directions every single time (e.g. z≈0.74-0.78 after a "reach" ramp whose true converged
    target is z≈0.85, and z≈0.81-0.82 after a "retract" ramp whose true target is z≈0.89) — the
    arm was always chasing, never arriving, because the next command always landed before the
    previous one had time to settle. run_pickup_smoke.py never hit this because it had separate
    explicit time.sleep() calls after its ramps; this folds that same hold into _ramp_arm
    itself so every caller gets it automatically.
    """
    for i in range(1, steps + 1):
        frac = i / steps
        pose = {k: from_pose[k] + frac * (to_pose[k] - from_pose[k]) for k in to_pose}
        runtime.send_arm_action(pose)
        await asyncio.sleep(step_dt)
    await asyncio.sleep(settle_s)


class VlmClientProtocol(Protocol):
    """Structural type so a FakeVlmClient (blueprint §18.2/§18.3) can stand in for VlmClient
    without inheriting from it — decouples control_loop tests from the real HTTP client."""

    async def decide(
        self,
        image,
        instruction: str,
        episode_id: str,
        step_index: int,
        previous_action: str | None = None,
        timeout_s: float | None = None,
    ): ...


async def _watchdog_task(watchdog: Watchdog, runtime: G1Runtime, trip_event: asyncio.Event) -> None:
    while not trip_event.is_set():
        if watchdog.must_trip():
            print(f"watchdog tripped: {watchdog.seconds_since_heartbeat():.2f}s since last heartbeat", flush=True)
            runtime.stop()
            trip_event.set()
            return
        await asyncio.sleep(0.1)


async def run_episode(
    runtime: G1Runtime,
    vlm_client: VlmClientProtocol,
    config: AppConfig,
    action_mapper: ActionMapper,
    recorder: Recorder,
) -> EpisodeResult:
    runtime.stop()
    runtime.reset()

    watchdog = Watchdog(timeout_s=config.control.heartbeat_timeout_s)
    trip_event = asyncio.Event()
    watchdog_handle = asyncio.create_task(_watchdog_task(watchdog, runtime, trip_event))

    previous_action = NavAction.STOP
    started_at = time.monotonic()
    steps: list[StepRecord] = []
    result: EpisodeResult | None = None

    try:
        for step_index in range(config.episode.max_steps):
            if trip_event.is_set():
                result = EpisodeResult.failure("watchdog_timeout")
                break

            frame = runtime.latest_frame()
            frame_safety = check_frame_safety(frame, config.safety)
            if frame_safety.must_stop:
                runtime.stop()
                result = EpisodeResult.failure(frame_safety.reason)
                break

            if time.monotonic() - started_at > config.episode.timeout_s:
                runtime.stop()
                result = EpisodeResult.failure("episode_timeout")
                break

            runtime.stop()
            await asyncio.sleep(config.control.stop_settle_s)

            frame = runtime.latest_frame()

            try:
                decision = await vlm_client.decide(
                    image=frame.rgb,
                    instruction=config.task.instruction,
                    episode_id=recorder.run_dir.name,
                    step_index=step_index,
                    previous_action=previous_action.value,
                    timeout_s=config.vlm.timeout_s,
                )
            except Exception as exc:
                print(f"vlm_client.decide() failed: {exc!r}", flush=True)
                runtime.stop()
                result = EpisodeResult.failure("vlm_error", detail=repr(exc))
                break

            watchdog.heartbeat()

            action = NavAction(decision.action) if decision.parse_ok else NavAction.STOP
            command = action_mapper.to_remote(action)

            command_safety = check_command_safety(command)
            if command_safety.must_stop:
                runtime.stop()
                result = EpisodeResult.failure(command_safety.reason)
                break

            if action == NavAction.GRASP:
                # Walking with the arm extended badly destabilizes locomotion (live run:
                # pelvis drifted sideways ~7.5x faster with the arm out — see conversation
                # record), but GRASP always runs from a full STOP, so that risk doesn't apply
                # here. Retract on failure so the *next* action (if it's a walk) isn't left
                # fighting an extended arm; leave it extended on success — carrying needs it.
                runtime.stop()
                await _ramp_arm(runtime, GRASP_REST_POSE, GRASP_REACH_POSE)
                print(f"  [diag] after reach ramp, wrist={runtime.object_xyz('right_wrist_yaw_link')}", flush=True)
                grasped = runtime.try_grasp(max_distance_m=GRASP_MAX_DISTANCE_M)
                if not grasped:
                    await _ramp_arm(runtime, GRASP_REACH_POSE, GRASP_REST_POSE)
                    print(f"  [diag] after retract ramp, wrist={runtime.object_xyz('right_wrist_yaw_link')}", flush=True)
            elif action == NavAction.RELEASE:
                runtime.release_grasp()
                await _ramp_arm(runtime, GRASP_REACH_POSE, GRASP_REST_POSE)
                print(f"  [diag] after release ramp, wrist={runtime.object_xyz('right_wrist_yaw_link')}", flush=True)
            else:
                runtime.send_remote(command)
                await asyncio.sleep(config.control.action_duration_s)
                runtime.stop()

            after_frame = runtime.latest_frame()
            target_distance_m = _target_distance_m(after_frame, config)
            is_grasping = runtime.is_grasping()

            recorder.record_step(
                step=step_index,
                instruction=config.task.instruction,
                raw_text=decision.raw_text,
                parsed_action=action.value,
                parse_ok=decision.parse_ok,
                remote_command=command,
                vlm_latency_ms=decision.latency_ms,
                frame_before=frame,
                target_distance_m=target_distance_m,
            )
            recorder.record_after_frame(step_index, after_frame)
            steps.append(StepRecord(
                action=action.value, parse_ok=decision.parse_ok,
                vlm_latency_ms=decision.latency_ms,
                roll_rad=frame.imu_roll, pitch_rad=frame.imu_pitch,
                target_distance_m=target_distance_m,
                is_grasping=is_grasping,
            ))

            previous_action = action

            if action == NavAction.STOP and config.episode.stop_action_terminates:
                result = EpisodeResult.from_stop_assessment(target_distance_m, config.task.success_radius_m)
                break
        else:
            result = EpisodeResult.failure("max_steps")
    finally:
        trip_event.set()
        watchdog_handle.cancel()
        runtime.stop()

    assert result is not None
    duration_s = time.monotonic() - started_at
    metrics = compute_metrics(result, steps, duration_s)
    recorder.finalize(metadata={"instruction": config.task.instruction}, metrics=metrics)
    return result
