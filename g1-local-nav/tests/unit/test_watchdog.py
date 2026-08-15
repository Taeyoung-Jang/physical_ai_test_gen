"""Unit tests for safety.py — Watchdog + frame/command safety checks (blueprint §13, §18.1)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np
import pytest

from g1_local_nav.config import SafetyConfig
from g1_local_nav.robot_runtime import RobotFrame
from g1_local_nav.safety import Watchdog, check_command_safety, check_frame_safety

SAFETY_CONFIG = SafetyConfig(max_abs_roll_rad=0.70, max_abs_pitch_rad=0.70, stale_camera_s=1.0)


def _make_frame(roll=0.0, pitch=0.0, age_s=0.0) -> RobotFrame:
    now_ns = time.time_ns()
    return RobotFrame(
        rgb=np.zeros((1, 1, 3), dtype=np.uint8),
        timestamp_ns=now_ns - int(age_s * 1e9),
        imu_roll=roll,
        imu_pitch=pitch,
        imu_yaw=0.0,
    )


def test_watchdog_does_not_trip_immediately() -> None:
    wd = Watchdog(timeout_s=1.0)
    assert not wd.must_trip()


def test_watchdog_trips_after_timeout() -> None:
    wd = Watchdog(timeout_s=0.05)
    time.sleep(0.1)
    assert wd.must_trip()


def test_watchdog_heartbeat_resets_timer() -> None:
    wd = Watchdog(timeout_s=0.1)
    time.sleep(0.05)
    wd.heartbeat()
    time.sleep(0.05)
    assert not wd.must_trip()  # 0.05s since last heartbeat, well under 0.1s timeout


def test_frame_safety_ok_within_thresholds() -> None:
    state = check_frame_safety(_make_frame(roll=0.1, pitch=0.1, age_s=0.1), SAFETY_CONFIG)
    assert state.must_stop is False


def test_frame_safety_stale_camera_trips() -> None:
    state = check_frame_safety(_make_frame(age_s=2.0), SAFETY_CONFIG)
    assert state.must_stop is True
    assert "stale_camera" in state.reason


@pytest.mark.parametrize("roll,pitch", [(0.9, 0.0), (0.0, 0.9), (-0.9, 0.0)])
def test_frame_safety_roll_pitch_exceeded_trips(roll: float, pitch: float) -> None:
    state = check_frame_safety(_make_frame(roll=roll, pitch=pitch), SAFETY_CONFIG)
    assert state.must_stop is True


def test_command_safety_ok_for_finite_values() -> None:
    state = check_command_safety({"remote.lx": 0.0, "remote.ly": 0.3})
    assert state.must_stop is False


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), float("-inf")])
def test_command_safety_rejects_non_finite(bad_value: float) -> None:
    state = check_command_safety({"remote.ly": bad_value})
    assert state.must_stop is True
    assert "non_finite_command" in state.reason


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
