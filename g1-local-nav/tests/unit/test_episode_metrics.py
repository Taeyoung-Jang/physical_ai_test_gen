"""Unit tests for the Milestone 6 ground-truth distance/success logic (blueprint §14.3):
EpisodeResult.from_stop_assessment() and metrics.compute_metrics()'s target-distance fields.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from g1_local_nav.episode import EpisodeResult
from g1_local_nav.metrics import StepRecord, compute_metrics


def test_stop_assessment_succeeds_within_radius() -> None:
    result = EpisodeResult.from_stop_assessment(target_distance_m=0.5, success_radius_m=0.7)
    assert result.outcome == "success"
    assert result.metadata["target_distance_m"] == 0.5


def test_stop_assessment_fails_outside_radius() -> None:
    result = EpisodeResult.from_stop_assessment(target_distance_m=1.2, success_radius_m=0.7)
    assert result.outcome == "failure"
    assert result.reason == "stopped_outside_target_radius"


def test_stop_assessment_at_exact_radius_boundary_succeeds() -> None:
    result = EpisodeResult.from_stop_assessment(target_distance_m=0.7, success_radius_m=0.7)
    assert result.outcome == "success"


def test_stop_assessment_without_ground_truth_is_honest_failure() -> None:
    result = EpisodeResult.from_stop_assessment(target_distance_m=None, success_radius_m=0.7)
    assert result.outcome == "failure"
    assert result.reason == "stopped_without_target_metric"


def _step(distance: float | None) -> StepRecord:
    return StepRecord(
        action="FORWARD", parse_ok=True, vlm_latency_ms=100.0,
        roll_rad=0.0, pitch_rad=0.0, target_distance_m=distance,
    )


def test_compute_metrics_reports_min_and_final_distance() -> None:
    steps = [_step(2.0), _step(1.5), _step(0.8), _step(1.0)]
    result = EpisodeResult.success(target_distance_m=1.0)
    metrics = compute_metrics(result, steps, duration_s=4.0)
    assert metrics["min_target_distance_m"] == 0.8
    assert metrics["final_target_distance_m"] == 1.0


def test_compute_metrics_distance_none_when_no_ground_truth() -> None:
    steps = [_step(None), _step(None)]
    result = EpisodeResult.failure("max_steps")
    metrics = compute_metrics(result, steps, duration_s=4.0)
    assert metrics["min_target_distance_m"] is None
    assert metrics["final_target_distance_m"] is None


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
