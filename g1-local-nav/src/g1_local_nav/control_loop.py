"""Core closed-loop algorithm (blueprint §12): sense -> decide -> act -> stop, chunked.

VLM inference does not run concurrently with movement — the robot STOPs before every camera
read and every decision, and only moves for a fixed action_duration_s before stopping again.
This is deliberate (blueprint §5.2): holding the previous command while waiting on a slow VLM
call would let the robot keep walking on stale intent, causing overshoot.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Protocol

from .action import NavAction
from .action_mapper import ActionMapper
from .config import AppConfig
from .episode import EpisodeResult
from .metrics import StepRecord, compute_metrics
from .recorder import Recorder
from .robot_runtime import G1Runtime
from .safety import Watchdog, check_command_safety, check_frame_safety
from .vlm_client import VlmClient

logger = logging.getLogger("control_loop")


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
            logger.warning(f"watchdog tripped: {watchdog.seconds_since_heartbeat():.2f}s since last heartbeat")
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
                logger.warning(f"vlm_client.decide() failed: {exc!r}")
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

            recorder.record_step(
                step=step_index,
                instruction=config.task.instruction,
                raw_text=decision.raw_text,
                parsed_action=action.value,
                parse_ok=decision.parse_ok,
                remote_command=command,
                vlm_latency_ms=decision.latency_ms,
                frame_before=frame,
            )
            steps.append(StepRecord(
                action=action.value, parse_ok=decision.parse_ok,
                vlm_latency_ms=decision.latency_ms,
                roll_rad=frame.imu_roll, pitch_rad=frame.imu_pitch,
            ))

            runtime.send_remote(command)
            await asyncio.sleep(config.control.action_duration_s)
            runtime.stop()

            recorder.record_after_frame(step_index, runtime.latest_frame())
            previous_action = action

            if action == NavAction.STOP and config.episode.stop_action_terminates:
                result = EpisodeResult.from_stop_assessment()
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
