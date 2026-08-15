"""Episode metrics computed from the recorded decision steps (blueprint §16).

target-distance fields (minimum/final distance to the red box) are NOT computed here — they
need the red-box scene's ground-truth position, which doesn't exist until Milestone 6. Listed
as None below rather than silently omitted, so it's visible in metrics.json that they're a
known gap, not an oversight.
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
        "min_target_distance_m": None,  # deferred to Milestone 6 (needs red-box scene)
        "final_target_distance_m": None,  # deferred to Milestone 6
        "max_abs_roll_rad": round(max((abs(s.roll_rad) for s in steps), default=0.0), 3),
        "max_abs_pitch_rad": round(max((abs(s.pitch_rad) for s in steps), default=0.0), 3),
        "fall_count": fall_count,
    }
