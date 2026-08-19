"""High-level navigation action space (blueprint §10.1), plus GRASP/RELEASE and BACKWARD — the
pick-and-carry extension beyond blueprint §14's navigate-and-stop scope. BACKWARD was added so a
"carry the box away" episode can step straight back from the pickup point instead of only
turning-then-forward (both work; BACKWARD is simpler to script/predict — see conversation
record). STRAFE/LOOK_AROUND are still explicitly deferred (blueprint §10.1, §23).

GRASP/RELEASE don't map to a locomotion remote command at all (see action_map.yaml — both are
zero-remote, same as STOP); control_loop.py branches on them to drive G1Runtime.try_grasp() /
release_grasp() and the arm-reach pose instead. Kept in this one enum anyway, not a separate
action space, because the VLM only ever emits one token per decision regardless of category —
splitting them would mean two parallel "what did the model say" paths for no benefit.
"""
from __future__ import annotations

from enum import StrEnum


class NavAction(StrEnum):
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"
    TURN_LEFT = "TURN_LEFT"
    TURN_RIGHT = "TURN_RIGHT"
    STOP = "STOP"
    GRASP = "GRASP"
    RELEASE = "RELEASE"
