"""Explicit rectangular subdomains shared by sampling and proposal guards.

These are search settings, never changes to physical scene schemas or verdicts.
No point/geometry/outcome rejection sampling is performed.
"""

import math

from .scene_space import axes_for_schema

VERSION = "bounded-scene-domain-v1"


def checked_domain(domain, schema=None):
    if not isinstance(domain, dict) or set(domain) != {
        "schema_version",
        "scene_schema",
        "axes",
        "scope",
    }:
        raise ValueError("explicit bounded scene domain contract required")
    if domain["schema_version"] != VERSION or (
        schema is not None and domain["scene_schema"] != schema
    ):
        raise ValueError("bounded scene domain version/schema mismatch")
    if not isinstance(domain["scope"], str) or not 1 <= len(domain["scope"].strip()) <= 500:
        raise ValueError("bounded scene domain scope required")
    physical = axes_for_schema(domain["scene_schema"])
    supplied = domain["axes"]
    if not isinstance(supplied, dict) or set(supplied) != set(physical):
        raise ValueError("bounded domain must specify every physical axis exactly once")
    axes = {}
    for axis, (lo, hi) in physical.items():
        bounds = supplied[axis]
        if (
            not isinstance(bounds, (list, tuple))
            or len(bounds) != 2
            or any(type(v) not in (int, float) or not math.isfinite(v) for v in bounds)
            or not lo <= bounds[0] < bounds[1] <= hi
        ):
            raise ValueError(
                f"invalid bounded axis {axis}; require physical lo <= low < high <= hi"
            )
        axes[axis] = tuple(bounds)
    return axes


def check_parameters(parameters, domain):
    axes = checked_domain(domain)
    if set(parameters) != set(axes) or any(
        type(parameters[a]) not in (int, float)
        or not math.isfinite(parameters[a])
        or not lo <= parameters[a] <= hi
        for a, (lo, hi) in axes.items()
    ):
        raise ValueError("candidate outside frozen shared scene domain")
