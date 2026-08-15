"""Integration test for control_loop.run_episode() — blueprint §18.2 "Fake VLM server + real
simulator", adapted: this uses a fake G1Runtime too, not the real MuJoCo one. The real
simulator needs `mjpython` + a GUI window (macOS constraint, see envs/SETUP_NOTES.md), which
can't run inside an automated pytest process. Exercising the real simulator with a fake VLM
client is scripts/run_closed_loop.sh's job (interactive, blueprint §17 Milestone 5) — this
file covers what CAN run headless: control_loop's own logic (termination conditions, safety
trips, watchdog, recorder wiring), using asyncio.run() directly rather than pytest-asyncio to
avoid a new dependency for four tests.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import numpy as np

from g1_local_nav.action_mapper import ActionMapper
from g1_local_nav.config import (
    AppConfig,
    ControlConfig,
    EpisodeConfig,
    LoggingConfig,
    RobotConfig,
    SafetyConfig,
    TaskConfig,
    VlmConfig,
)
from g1_local_nav.control_loop import run_episode
from g1_local_nav.recorder import Recorder
from g1_local_nav.robot_runtime import RobotFrame
from g1_local_nav.vlm_client import FakeVlmClient


class FakeG1Runtime:
    """Stands in for G1Runtime — no MuJoCo, no mjpython, just tracks calls."""

    def __init__(self, roll: float = 0.0, pitch: float = 0.0):
        self.stop_calls = 0
        self.reset_calls = 0
        self.sent_commands: list[dict[str, float]] = []
        self._roll = roll
        self._pitch = pitch

    def latest_frame(self) -> RobotFrame:
        return RobotFrame(
            rgb=np.zeros((4, 4, 3), dtype=np.uint8),
            timestamp_ns=time.time_ns(),
            imu_roll=self._roll,
            imu_pitch=self._pitch,
            imu_yaw=0.0,
        )

    def send_remote(self, command: dict) -> None:
        self.sent_commands.append(dict(command))

    def stop(self) -> None:
        self.stop_calls += 1

    def reset(self) -> None:
        self.reset_calls += 1


def _make_config(**overrides) -> AppConfig:
    base = dict(
        robot=RobotConfig("head_camera", 5555, "localhost", 640, 480, 30, 5),
        vlm=VlmConfig("http://127.0.0.1:8000", 8.0),
        control=ControlConfig(action_duration_s=0.01, stop_settle_s=0.01, heartbeat_timeout_s=5.0),
        safety=SafetyConfig(max_abs_roll_rad=0.70, max_abs_pitch_rad=0.70, stale_camera_s=1.0),
        episode=EpisodeConfig(timeout_s=30.0, max_steps=12, stop_action_terminates=False),
        task=TaskConfig("Move toward the red box and stop near it."),
        logging=LoggingConfig("runs", True, True),
    )
    base.update(overrides)
    return AppConfig(**base)


def test_runs_at_least_ten_sense_decide_act_cycles(tmp_path: Path) -> None:
    # blueprint §17 Milestone 5 completion criterion: "최소 10회의 sense-decide-act cycle 수행"
    runtime = FakeG1Runtime()
    vlm = FakeVlmClient(script=["FORWARD"] * 12)
    config = _make_config()
    mapper = ActionMapper()
    recorder = Recorder(tmp_path, "test_ep_max_steps", save_all_frames=False)

    result = asyncio.run(run_episode(runtime, vlm, config, mapper, recorder))

    assert result.outcome == "failure"
    assert result.reason == "max_steps"
    assert len(runtime.sent_commands) >= 10
    assert runtime.reset_calls == 1


def test_roll_exceeded_stops_episode_early(tmp_path: Path) -> None:
    runtime = FakeG1Runtime(roll=0.9)  # exceeds default 0.70 threshold immediately
    vlm = FakeVlmClient(script=["FORWARD"] * 12)
    config = _make_config()
    mapper = ActionMapper()
    recorder = Recorder(tmp_path, "test_ep_roll", save_all_frames=False)

    result = asyncio.run(run_episode(runtime, vlm, config, mapper, recorder))

    assert result.outcome == "failure"
    assert "roll_exceeded" in result.reason
    assert len(runtime.sent_commands) == 0  # tripped before ever sending a command


def test_vlm_error_resolves_to_stop(tmp_path: Path) -> None:
    class RaisingVlmClient:
        async def decide(self, **kwargs):
            raise TimeoutError("simulated VLM timeout")

    runtime = FakeG1Runtime()
    config = _make_config()
    mapper = ActionMapper()
    recorder = Recorder(tmp_path, "test_ep_vlm_error", save_all_frames=False)

    result = asyncio.run(run_episode(runtime, RaisingVlmClient(), config, mapper, recorder))

    assert result.outcome == "failure"
    assert result.reason == "vlm_error"
    assert runtime.stop_calls >= 1
    assert len(runtime.sent_commands) == 0


def test_stop_action_terminates_when_configured(tmp_path: Path) -> None:
    runtime = FakeG1Runtime()
    vlm = FakeVlmClient(script=["FORWARD", "FORWARD", "STOP"])
    config = _make_config(episode=EpisodeConfig(timeout_s=30.0, max_steps=12, stop_action_terminates=True))
    mapper = ActionMapper()
    recorder = Recorder(tmp_path, "test_ep_stop_terminate", save_all_frames=False)

    result = asyncio.run(run_episode(runtime, vlm, config, mapper, recorder))

    assert result.outcome == "failure"
    assert result.reason == "stopped_without_target_metric"
    assert len(runtime.sent_commands) == 3  # FORWARD, FORWARD, STOP — then terminated


def test_metrics_and_decisions_log_written(tmp_path: Path) -> None:
    runtime = FakeG1Runtime()
    vlm = FakeVlmClient(script=["FORWARD"] * 12)
    config = _make_config()
    mapper = ActionMapper()
    recorder = Recorder(tmp_path, "test_ep_artifacts", save_all_frames=False)

    asyncio.run(run_episode(runtime, vlm, config, mapper, recorder))

    assert (recorder.run_dir / "metrics.json").exists()
    assert (recorder.run_dir / "metadata.json").exists()
    assert (recorder.run_dir / "summary.md").exists()
    decisions = (recorder.run_dir / "decisions.jsonl").read_text().strip().splitlines()
    assert len(decisions) == 12


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
