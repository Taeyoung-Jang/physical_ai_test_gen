"""Streaming behavioral observations, independent of goal success/failure.

Contact episodes are grouped by geom pair and execution phase, not physics tick.
Impulse is the sum of normal forces over all simultaneous contact points * dt.
"""

import json
from collections import Counter, deque
from copy import deepcopy


class BehaviorEvents:
    def __init__(self, stream):
        self.stream = stream
        self.active = {}
        self.counts = Counter()
        self.recent = deque(maxlen=24)
        self.peak_force_n = 0.0
        self.normal_impulse_ns = 0.0

    def emit(self, event, time_s, phase, **details):
        row = {"event": event, "time_s": time_s, "phase": phase, **details}
        self.stream.write(json.dumps(row, allow_nan=False) + "\n")
        self.stream.flush()
        self.recent.append(row)
        self.counts[event] += 1

    def update(self, conditions, time_s, phase, dt):
        for key in list(self.active):
            if key not in conditions:
                self._end(key, time_s, phase, truncated=False)
        for key, details in conditions.items():
            kind = details["kind"]
            if key not in self.active:
                self.active[key] = {
                    **details,
                    "start_s": time_s,
                    "start_phase": phase,
                    "sampled_duration_s": 0.0,
                    "peak_normal_force_n": 0.0,
                    "normal_impulse_ns": 0.0,
                }
                self.emit(kind + "_start", time_s, phase, **details)
            episode = self.active[key]
            episode["sampled_duration_s"] += dt
            force = details.get("peak_normal_force_n", 0.0)
            impulse = details.get("sum_normal_force_n", 0.0) * dt
            episode["peak_normal_force_n"] = max(episode["peak_normal_force_n"], force)
            episode["normal_impulse_ns"] += impulse
            self.peak_force_n = max(self.peak_force_n, force)
            self.normal_impulse_ns += impulse

    def _end(self, key, time_s, phase, *, truncated):
        episode = self.active.pop(key)
        kind = episode["kind"]
        self.emit(kind + "_end", time_s, phase, **episode, truncated=truncated)
        if kind == "fall" and not truncated:
            self.emit("upright_recovered", time_s, phase)

    def close(self, time_s, phase):
        for key in list(self.active):
            self._end(key, time_s, phase, truncated=True)

    def summary(self):
        return {
            "counts": dict(self.counts),
            "peak_normal_force_n": self.peak_force_n,
            "normal_impulse_ns": self.normal_impulse_ns,
            "scope": "robot/world contacts only; force peak per contact point; impulse summed",
        }

    def observation(self):
        # Inference runs concurrently with physics; an observation must remain a snapshot.
        return deepcopy(
            {
                "summary": self.summary(),
                "recent": list(self.recent),
                "active": list(self.active.values())[:32],
            }
        )
