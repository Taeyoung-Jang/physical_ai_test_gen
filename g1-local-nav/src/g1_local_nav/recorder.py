"""Episode logging (blueprint §16). One directory per episode under runs/, decisions.jsonl
plus optional before/after frame JPEGs. Deliberately does not serialize full raw observations
— only images and the scalar fields blueprint §20 rule 9 calls out ("이미지와 핵심 scalar만
기록한다").
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

from .robot_runtime import RobotFrame


class Recorder:
    def __init__(self, root_dir: Path | str, episode_id: str, save_all_frames: bool = True):
        ts = time.strftime("%Y-%m-%dT%H%M%SZ", time.gmtime())
        self.run_dir = Path(root_dir) / f"{ts}_{episode_id}"
        self.frames_dir = self.run_dir / "frames"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.frames_dir.mkdir(exist_ok=True)
        self._save_all_frames = save_all_frames
        self._decisions_path = self.run_dir / "decisions.jsonl"
        self._decisions_path.touch()
        self._step_count = 0

    def record_step(
        self,
        step: int,
        instruction: str,
        raw_text: str,
        parsed_action: str,
        parse_ok: bool,
        remote_command: dict[str, float],
        vlm_latency_ms: float,
        frame_before: RobotFrame,
        target_distance_m: float | None = None,
    ) -> None:
        camera_age_ms = (time.time_ns() - frame_before.timestamp_ns) / 1e6
        record: dict[str, Any] = {
            "episode_id": self.run_dir.name,
            "step": step,
            "instruction": instruction,
            "raw_text": raw_text,
            "parsed_action": parsed_action,
            "parse_ok": parse_ok,
            "remote_command": remote_command,
            "vlm_latency_ms": vlm_latency_ms,
            "camera_age_ms": camera_age_ms,
            "roll_rad": frame_before.imu_roll,
            "pitch_rad": frame_before.imu_pitch,
            "target_distance_m": target_distance_m,
        }
        with self._decisions_path.open("a") as f:
            f.write(json.dumps(record) + "\n")

        if self._save_all_frames:
            Image.fromarray(frame_before.rgb).save(self.frames_dir / f"step_{step:03d}_before.jpg")

        self._step_count += 1

    def record_after_frame(self, step: int, frame: RobotFrame) -> None:
        if self._save_all_frames:
            Image.fromarray(frame.rgb).save(self.frames_dir / f"step_{step:03d}_after.jpg")

    def finalize(self, metadata: dict[str, Any], metrics: dict[str, Any]) -> None:
        (self.run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        (self.run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        summary_lines = [f"# Episode {self.run_dir.name}", ""]
        for key, value in metrics.items():
            summary_lines.append(f"- **{key}**: {value}")
        (self.run_dir / "summary.md").write_text("\n".join(summary_lines) + "\n")
