"""Unit tests for config loading (blueprint §18.1)."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from g1_local_nav.config import load_config

VALID_YAML = textwrap.dedent("""
    robot:
      camera_name: head_camera
      camera_port: 5555
      camera_server_address: localhost
      camera_width: 640
      camera_height: 480
      camera_fps: 30
      camera_warmup_s: 5
    vlm:
      base_url: http://127.0.0.1:8000
      timeout_s: 8.0
    control:
      action_duration_s: 0.30
      stop_settle_s: 0.15
      heartbeat_timeout_s: 1.0
    safety:
      max_abs_roll_rad: 0.70
      max_abs_pitch_rad: 0.70
      stale_camera_s: 1.0
    episode:
      timeout_s: 60.0
      max_steps: 80
      stop_action_terminates: false
    task:
      instruction: "Move toward the red box and stop near it."
    logging:
      root_dir: runs
      save_all_frames: true
      save_raw_model_output: true
    """)


def test_default_config_loads() -> None:
    config = load_config()
    assert config.robot.camera_name == "head_camera"
    assert config.robot.camera_port == 5555
    assert config.vlm.base_url.startswith("http://")
    assert config.episode.max_steps > 0


def test_loaded_values_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "app.yaml"
    path.write_text(VALID_YAML)
    config = load_config(path)
    assert config.robot.camera_port == 5555
    assert config.control.action_duration_s == 0.30
    assert config.safety.max_abs_roll_rad == 0.70
    assert config.episode.stop_action_terminates is False
    assert config.task.instruction == "Move toward the red box and stop near it."


def test_missing_top_level_section_raises(tmp_path: Path) -> None:
    # robot: is complete, but every other top-level section is absent.
    path = tmp_path / "incomplete.yaml"
    path.write_text(textwrap.dedent("""
        robot:
          camera_name: head_camera
          camera_port: 5555
          camera_server_address: localhost
          camera_width: 640
          camera_height: 480
          camera_fps: 30
          camera_warmup_s: 5
        """))
    with pytest.raises(KeyError):
        load_config(path)


def test_missing_field_within_section_raises(tmp_path: Path) -> None:
    # robot: is present but missing camera_port — should fail constructing RobotConfig.
    path = tmp_path / "incomplete_fields.yaml"
    path.write_text(textwrap.dedent("""
        robot:
          camera_name: head_camera
          camera_server_address: localhost
          camera_width: 640
          camera_height: 480
          camera_fps: 30
          camera_warmup_s: 5
        vlm:
          base_url: http://127.0.0.1:8000
          timeout_s: 8.0
        control:
          action_duration_s: 0.30
          stop_settle_s: 0.15
          heartbeat_timeout_s: 1.0
        safety:
          max_abs_roll_rad: 0.70
          max_abs_pitch_rad: 0.70
          stale_camera_s: 1.0
        episode:
          timeout_s: 60.0
          max_steps: 80
          stop_action_terminates: false
        task:
          instruction: "Move toward the red box and stop near it."
        logging:
          root_dir: runs
          save_all_frames: true
          save_raw_model_output: true
        """))
    with pytest.raises(TypeError):
        load_config(path)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
