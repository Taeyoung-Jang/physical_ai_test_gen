"""Optional simulation deadline; omitted means no simulation-time limit."""

import math


def simulation_limit(seconds):
    if seconds is None:
        return math.inf
    if not math.isfinite(seconds) or seconds < 3:
        raise ValueError("max-seconds must be finite and >=3, or omitted for unlimited")
    return float(seconds)
