"""Episode metrics computed from the recorded decision steps (blueprint §16).

target-distance fields (minimum/final distance to the red box) come from each StepRecord's
target_distance_m, which is None whenever ground-truth base position wasn't available for that
step (e.g. FakeG1Runtime in tests, or the default upstream scene without a target) — in that
case both fields stay None here too, rather than silently reporting a bogus 0.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .episode import EpisodeResult


@dataclass
class StepRecord:
    action: str
    parse_ok: bool
    vlm_latency_ms: float
    roll_rad: float
    pitch_rad: float
    target_distance_m: float | None = None
    is_grasping: bool = False


def compute_metrics(
    result: EpisodeResult,
    steps: list[StepRecord],
    duration_s: float,
    fall_count: int = 0,
) -> dict[str, Any]:
    latencies = np.array([s.vlm_latency_ms for s in steps]) if steps else np.array([0.0])
    action_histogram: dict[str, int] = {}
    for s in steps:
        action_histogram[s.action] = action_histogram.get(s.action, 0) + 1

    target_distances = [s.target_distance_m for s in steps if s.target_distance_m is not None]

    return {
        "outcome": result.outcome,
        "failure_reason": result.reason,
        "episode_duration_s": round(duration_s, 3),
        "num_vlm_decisions": len(steps),
        "action_histogram": action_histogram,
        "invalid_output_count": sum(1 for s in steps if not s.parse_ok),
        "vlm_latency_ms_mean": round(float(latencies.mean()), 1),
        "vlm_latency_ms_p50": round(float(np.median(latencies)), 1),
        "vlm_latency_ms_p95": round(float(np.percentile(latencies, 95)), 1),
        "min_target_distance_m": round(min(target_distances), 3) if target_distances else None,
        "final_target_distance_m": round(target_distances[-1], 3) if target_distances else None,
        "max_abs_roll_rad": round(max((abs(s.roll_rad) for s in steps), default=0.0), 3),
        "max_abs_pitch_rad": round(max((abs(s.pitch_rad) for s in steps), default=0.0), 3),
        "fall_count": fall_count,
        "ever_grasped": any(s.is_grasping for s in steps),
    }
