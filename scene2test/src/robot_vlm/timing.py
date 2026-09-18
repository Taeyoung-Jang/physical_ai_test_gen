"""Explicit goal-agent request timing; simulation budget is independent."""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestTiming:
    read_s: float = 90.0

    def __post_init__(self):
        if not math.isfinite(self.read_s) or not 1 <= self.read_s <= 300:
            raise ValueError("response-timeout must be finite, 1..300 seconds")

    @property
    def deadline_s(self):
        # Connect/write/pool timeout allowances and scheduling/parse margin.
        return self.read_s + 30.0
