"""Unit tests for ActionMapper — pure YAML-driven logic, no simulator/robot needed."""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from g1_local_nav.action import NavAction
from g1_local_nav.action_mapper import ActionMapper

REMOTE_AXES = ("remote.lx", "remote.ly", "remote.rx", "remote.ry")


@pytest.fixture
def mapper() -> ActionMapper:
    return ActionMapper(Path(__file__).resolve().parents[2] / "configs" / "action_map.yaml")


def test_all_nav_actions_present(mapper: ActionMapper) -> None:
    for action in NavAction:
        command = mapper.to_remote(action)
        assert set(command.keys()) == set(REMOTE_AXES)


def test_stop_is_all_zero(mapper: ActionMapper) -> None:
    command = mapper.to_remote(NavAction.STOP)
    assert all(v == 0.0 for v in command.values())


def test_forward_has_positive_ly(mapper: ActionMapper) -> None:
    command = mapper.to_remote(NavAction.FORWARD)
    assert command["remote.ly"] > 0.0
    assert command["remote.lx"] == 0.0
    assert command["remote.rx"] == 0.0


def test_turn_left_and_right_are_opposite_sign(mapper: ActionMapper) -> None:
    left = mapper.to_remote(NavAction.TURN_LEFT)
    right = mapper.to_remote(NavAction.TURN_RIGHT)
    assert left["remote.rx"] != 0.0
    assert left["remote.rx"] == -right["remote.rx"]


def test_clamp_enforced(tmp_path: Path) -> None:
    config = tmp_path / "action_map.yaml"
    config.write_text(
        textwrap.dedent("""
        commands:
          FORWARD: {remote.lx: 0.0, remote.ly: 5.0, remote.rx: 0.0, remote.ry: 0.0}
          TURN_LEFT: {remote.lx: 0.0, remote.ly: 0.0, remote.rx: -5.0, remote.ry: 0.0}
          TURN_RIGHT: {remote.lx: 0.0, remote.ly: 0.0, remote.rx: 5.0, remote.ry: 0.0}
          STOP: {remote.lx: 0.0, remote.ly: 0.0, remote.rx: 0.0, remote.ry: 0.0}
        limits:
          remote.lx: [-0.35, 0.35]
          remote.ly: [-0.40, 0.40]
          remote.rx: [-0.35, 0.35]
          remote.ry: [-0.35, 0.35]
        """)
    )
    mapper = ActionMapper(config)
    command = mapper.to_remote(NavAction.FORWARD)
    assert command["remote.ly"] == 0.40  # clamped from 5.0 down to the configured max


def test_missing_action_raises(tmp_path: Path) -> None:
    config = tmp_path / "incomplete.yaml"
    config.write_text(
        textwrap.dedent("""
        commands:
          STOP: {remote.lx: 0.0, remote.ly: 0.0, remote.rx: 0.0, remote.ry: 0.0}
        limits:
          remote.lx: [-0.35, 0.35]
          remote.ly: [-0.40, 0.40]
          remote.rx: [-0.35, 0.35]
          remote.ry: [-0.35, 0.35]
        """)
    )
    with pytest.raises(ValueError, match="missing entries"):
        ActionMapper(config)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
