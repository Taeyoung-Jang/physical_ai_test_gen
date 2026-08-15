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
    def from_stop_assessment(cls) -> "EpisodeResult":
        # blueprint §14.3's ground-truth ||robot - target|| success check needs the red-box
        # scene's target position, which doesn't exist until Milestone 6. Until then a STOP
        # action can't be assessed as success/failure — reporting it honestly as "no metric to
        # judge by" rather than guessing.
        return cls(outcome="failure", reason="stopped_without_target_metric")
