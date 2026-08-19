"""Loads configs/app.yaml into typed, nested dataclasses. One loader for the whole app config —
unlike action_map.yaml (kept separate deliberately, see action_mapper.py), this one is shared
across control_loop.py, safety.py, recorder.py, cli.py, so a single typed structure avoids
each of them re-parsing raw dicts with their own key-typo risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "configs" / "app.yaml"


@dataclass(frozen=True)
class RobotConfig:
    camera_name: str
    camera_port: int
    camera_server_address: str
    camera_width: int
    camera_height: int
    camera_fps: int
    camera_warmup_s: int


@dataclass(frozen=True)
class VlmConfig:
    base_url: str
    timeout_s: float


@dataclass(frozen=True)
class ControlConfig:
    action_duration_s: float
    stop_settle_s: float
    heartbeat_timeout_s: float


@dataclass(frozen=True)
class SafetyConfig:
    max_abs_roll_rad: float
    max_abs_pitch_rad: float
    stale_camera_s: float


@dataclass(frozen=True)
class EpisodeConfig:
    timeout_s: float
    max_steps: int
    stop_action_terminates: bool


@dataclass(frozen=True)
class TaskConfig:
    instruction: str
    # Ground-truth target position (blueprint §14.3) — matches the navigation_target body in
    # assets/scenes/g1_hub/assets/scene_43dof_with_target.xml (pos="2.0 0.0 0.15"). Defaults
    # keep every pre-Milestone-6 caller (positional TaskConfig("...") in tests, old configs)
    # working unchanged. Only meaningful when G1_LOCAL_NAV_SCENE is set — the default upstream
    # scene has no target, so distance/success against these values is not meaningful there.
    target_x: float = 2.0
    target_y: float = 0.0
    success_radius_m: float = 0.7


@dataclass(frozen=True)
class LoggingConfig:
    root_dir: str
    save_all_frames: bool
    save_raw_model_output: bool


@dataclass(frozen=True)
class AppConfig:
    robot: RobotConfig
    vlm: VlmConfig
    control: ControlConfig
    safety: SafetyConfig
    episode: EpisodeConfig
    task: TaskConfig
    logging: LoggingConfig


def load_config(path: Path | str = DEFAULT_CONFIG_PATH) -> AppConfig:
    data = yaml.safe_load(Path(path).read_text())
    return AppConfig(
        robot=RobotConfig(**data["robot"]),
        vlm=VlmConfig(**data["vlm"]),
        control=ControlConfig(**data["control"]),
        safety=SafetyConfig(**data["safety"]),
        episode=EpisodeConfig(**data["episode"]),
        task=TaskConfig(**data["task"]),
        logging=LoggingConfig(**data["logging"]),
    )
