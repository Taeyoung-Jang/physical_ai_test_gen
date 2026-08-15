"""Safety checks and watchdog (blueprint §13). Every failure mode here resolves to STOP — no
retries, no partial recovery. Pure logic, no simulator/GUI dependency, so it's fully unit
testable (tests/unit/test_watchdog.py).
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from .config import SafetyConfig
from .robot_runtime import RobotFrame


@dataclass(frozen=True)
class SafetyState:
    must_stop: bool
    reason: str | None = None


def check_frame_safety(
    frame: RobotFrame, config: SafetyConfig, now_ns: int | None = None
) -> SafetyState:
    """Roll/pitch threshold + stale-camera check, from the latest observed frame."""
    now_ns = now_ns if now_ns is not None else time.time_ns()

    age_s = (now_ns - frame.timestamp_ns) / 1e9
    if age_s > config.stale_camera_s:
        return SafetyState(must_stop=True, reason=f"stale_camera({age_s:.2f}s)")

    if abs(frame.imu_roll) > config.max_abs_roll_rad:
        return SafetyState(must_stop=True, reason=f"roll_exceeded({frame.imu_roll:.3f}rad)")
    if abs(frame.imu_pitch) > config.max_abs_pitch_rad:
        return SafetyState(must_stop=True, reason=f"pitch_exceeded({frame.imu_pitch:.3f}rad)")

    return SafetyState(must_stop=False)


def check_command_safety(command: dict[str, float]) -> SafetyState:
    """NaN/Inf guard — never let a broken command reach G1Runtime.send_remote()."""
    for key, value in command.items():
        if not math.isfinite(value):
            return SafetyState(must_stop=True, reason=f"non_finite_command({key}={value})")
    return SafetyState(must_stop=False)


class Watchdog:
    """Tracks the last successful high-level heartbeat (blueprint §13.2).

    Only tracks state and reports must_trip() — deliberately does not itself zero remote axes
    or log anything, so the side effects stay visible at the call site (control_loop.py) rather
    than hidden inside this class.
    """

    def __init__(self, timeout_s: float):
        self._timeout_s = timeout_s
        self._last_heartbeat = time.monotonic()

    def heartbeat(self) -> None:
        self._last_heartbeat = time.monotonic()

    def seconds_since_heartbeat(self) -> float:
        return time.monotonic() - self._last_heartbeat

    def must_trip(self) -> bool:
        return self.seconds_since_heartbeat() > self._timeout_s
