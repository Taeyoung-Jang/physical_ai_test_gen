"""Episode lifecycle result (blueprint §12)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EpisodeResult:
    outcome: str  # "success" | "failure"
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def success(cls, **metadata: Any) -> "EpisodeResult":
        return cls(outcome="success", reason=None, metadata=metadata)

    @classmethod
    def failure(cls, reason: str, **metadata: Any) -> "EpisodeResult":
        return cls(outcome="failure", reason=reason, metadata=metadata)

    @classmethod
    def from_stop_assessment(cls, target_distance_m: float | None, success_radius_m: float) -> "EpisodeResult":
        """blueprint §14.3's ground-truth ||robot - target|| check, run when the robot itself
        decides to STOP. target_distance_m is None whenever ground-truth base position isn't
        available (e.g. FakeG1Runtime in tests, the default upstream scene without a target, or
        anything other than the real MuJoCo sim) — reported honestly as "no metric to judge by"
        rather than guessing.
        """
        if target_distance_m is None:
            return cls(outcome="failure", reason="stopped_without_target_metric")
        if target_distance_m <= success_radius_m:
            return cls.success(target_distance_m=round(target_distance_m, 3), success_radius_m=success_radius_m)
        return cls.failure(
            "stopped_outside_target_radius",
            target_distance_m=round(target_distance_m, 3),
            success_radius_m=success_radius_m,
        )
