"""Editable starter courses, intentionally modest defaults (not success guarantees)."""

from copy import deepcopy

PRESETS = {
    "flat": [{"kind": "flat", "length_m": 4}],
    "ramp": [{"kind": "ramp", "length_m": 2, "angle_deg": 5, "landing_m": 1}],
    "stairs": [{"kind": "stairs", "step_height_m": 0.04, "tread_m": 0.6, "count": 3}],
    "low_friction": [{"kind": "friction", "length_m": 4, "friction": 0.15}],
    "rough": [{"kind": "rough", "length_m": 4, "amplitude_m": 0.04, "cell_length_m": 0.5}],
    "slalom": [
        {
            "kind": "obstacles",
            "length_m": 8,
            "count": 3,
            "pattern": "slalom",
            "size_min_m": [0.2, 0.3, 0.2],
            "size_max_m": [0.7, 0.7, 1.3],
        }
    ],
    "bottleneck": [{"kind": "bottleneck", "length_m": 4, "gap_m": 1.8}],
}
PRESETS["mixed"] = [
    *PRESETS["ramp"],
    {"kind": "stairs", "step_height_m": 0.04, "count": 2, "tread_m": 0.6},
    {"kind": "friction", "length_m": 2, "friction": 0.2},
    {"kind": "rough", "length_m": 2, "amplitude_m": 0.03},
    {"kind": "obstacles", "length_m": 4, "count": 2, "pattern": "slalom"},
]


def preset(name, seed=0):
    return {"seed": seed, "width_m": 3.0, "friction": 0.8, "segments": deepcopy(PRESETS[name])}


def apply_parameters(settings, parameters):
    """Strict dot-path parameter application, shared by sampling and future AFS callers."""
    result = deepcopy(settings)
    for path, value in parameters.items():
        parts = path.split(".")
        target = result
        for part in parts[:-1]:
            target = target[int(part)] if isinstance(target, list) else target[part]
        key = int(parts[-1]) if isinstance(target, list) else parts[-1]
        if not isinstance(target, list) and key not in target:
            raise ValueError(f"parameter path must already exist in course: {path}")
        target[key] = value
    return result
