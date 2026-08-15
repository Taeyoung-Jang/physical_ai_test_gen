"""High-level navigation action space (blueprint §10.1). Kept to 4 actions for v1 —
BACKWARD/STRAFE/LOOK_AROUND are explicitly deferred (blueprint §10.1, §23)."""
from __future__ import annotations

from enum import StrEnum


class NavAction(StrEnum):
    FORWARD = "FORWARD"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    STOP = "STOP"
