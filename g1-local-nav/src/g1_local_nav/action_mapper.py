"""Loads configs/action_map.yaml and converts a NavAction into a clamped remote command dict.

Kept separate from robot_runtime.py so that command tuning (speed, turn rate, sign) is a YAML
edit, never a code change — this is what blueprint §10.2 and Milestone 2's completion criteria
("action map YAML 수정만으로 속도·부호 조정 가능") ask for.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .action import NavAction

DEFAULT_ACTION_MAP_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "action_map.yaml"


class ActionMapper:
    def __init__(self, config_path: Path | str = DEFAULT_ACTION_MAP_PATH):
        data = yaml.safe_load(Path(config_path).read_text())
        self._commands: dict[str, dict[str, float]] = data["commands"]
        self._limits: dict[str, tuple[float, float]] = {
            k: (v[0], v[1]) for k, v in data["limits"].items()
        }
        missing = [a for a in NavAction if a.value not in self._commands]
        if missing:
            raise ValueError(f"action_map.yaml missing entries for: {missing}")

    def to_remote(self, action: NavAction) -> dict[str, float]:
        raw = self._commands[action.value]
        return {
            axis: self._clamp(axis, value)
            for axis, value in raw.items()
        }

    def _clamp(self, axis: str, value: float) -> float:
        if axis not in self._limits:
            return value
        lo, hi = self._limits[axis]
        return max(lo, min(hi, value))
