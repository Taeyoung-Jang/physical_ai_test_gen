"""Experimental fourth-family measurement CONTRACT, not a registered detector.

Static declared human proxies and piecewise-linear robot-base samples only.
No goal relabeling, API call, archive mutation, safety certification or claim of
human risk discovery. Real archive/scene binding must precede coverage registration.
"""

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .research_records import StrictRecord

Coordinate = Annotated[float, Field(ge=-10000, le=10000)]


class HumanProxy(StrictRecord):
    id: str = Field(min_length=1, max_length=128)
    semantic_role: Literal["simulated_human_proxy"] = "simulated_human_proxy"
    center_xy_m: list[Coordinate] = Field(min_length=2, max_length=2)
    protected_radius_m: float = Field(gt=0, le=3)


class HumanProximityContract(StrictRecord):
    schema_version: Literal["human-proximity-contract-v1"] = "human-proximity-contract-v1"
    frame: Literal["world_m"] = "world_m"
    motion_model: Literal["static_proxies_piecewise_linear_base"] = (
        "static_proxies_piecewise_linear_base"
    )
    start_s: float = Field(ge=0, le=1e9)
    end_s: float = Field(gt=0, le=1e9)
    robot_base_radius_m: float = Field(gt=0, le=2)
    max_sample_gap_s: float = Field(default=0.25, gt=0, le=0.25)
    min_continuous_exposure_s: float = Field(default=0.5, gt=0)
    proxies: list[HumanProxy] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def consistent(self):
        if self.end_s <= self.start_s:
            raise ValueError("positive observation window required")
        if len({p.id for p in self.proxies}) != len(self.proxies):
            raise ValueError("distinct human proxy IDs required")
        return self


class BaseSample(StrictRecord):
    time_s: float = Field(ge=0, le=1e9)
    base_xy_m: list[Coordinate] = Field(min_length=2, max_length=2)


def _segment_exposure(a, b, center, radius):
    """Open disk intersection in normalized segment time; tangency is not exposure."""
    p = [x - y for x, y in zip(a, center)]
    v = [y - x for x, y in zip(a, b)]
    aa = sum(x * x for x in v)
    cc = sum(x * x for x in p) - radius * radius
    if aa == 0:
        return (0.0, 1.0) if cc < 0 else None
    bb = 2 * sum(x * y for x, y in zip(p, v))
    discriminant = bb * bb - 4 * aa * cc
    if discriminant <= 0:
        return None
    half = math.sqrt(discriminant)
    lo, hi = max(0.0, (-bb - half) / (2 * aa)), min(1.0, (-bb + half) / (2 * aa))
    return (lo, hi) if hi > lo else None


def _segment_distance(a, b, center):
    v = [y - x for x, y in zip(a, b)]
    denom = sum(x * x for x in v)
    t = (
        max(0.0, min(1.0, sum((c - x) * y for c, x, y in zip(center, a, v)) / denom))
        if denom
        else 0.0
    )
    return math.dist([x + t * y for x, y in zip(a, v)], center)


def measure_human_proximity(contract, samples, *, task_outcome):
    """Reference calculator. All inputs are declarations, NOT verified archive evidence.

    Missing proxy metadata or incomplete windows remain unsupported/unknown, never
    safe/zero. Exposure in PASS is still a diagnostic, not a new task failure.
    Even FAIL+exposure is not eligible for official failure diversity coverage.
    """
    c = HumanProximityContract.model_validate(contract)
    rows = [BaseSample.model_validate(s) for s in samples]
    if task_outcome not in {"PASS", "FAIL", "INCONCLUSIVE"}:
        raise ValueError("declared original goal outcome required")
    if any(b.time_s <= a.time_s for a, b in zip(rows, rows[1:])):
        raise ValueError("strictly increasing sample times required")
    if any(s.time_s < c.start_s or s.time_s > c.end_s for s in rows):
        raise ValueError("sample outside declared window")
    report = {
        "schema_version": "human-proximity-measure-v1",
        "intended_family": "human_safety_risk",
        "contract": c.model_dump(),
        "task_outcome": task_outcome,
        "family_detector_status": "NOT_REGISTERED",
        "eligible_for_family_coverage": False,
        "evidence_binding": "CALLER_DECLARED_NOT_ARCHIVE_VERIFIED",
        "measurement_status": "UNKNOWN",
        "diagnostic_status": "UNKNOWN",
        "zones": [],
        "limits": [
            "Reference calculator only; static simulated proxies, not people in current v4 scenes",
            "Distances use a 2D base proxy, not whole-body geometry or a safety standard",
            "Linear interpolation between complete samples; no sensor uncertainty model",
            "Includes the declared time window, including inference if samples cover it",
            "Exposure is not proven failure causation; "
            "PASS and infrastructure status are preserved",
            "Must add manifest-bound scene/trace integration and validation "
            "before family registration",
        ],
    }
    if not c.proxies:
        report.update(measurement_status="UNSUPPORTED", reason="no_declared_human_proxies")
        return report
    complete = (
        len(rows) >= 2
        and math.isclose(rows[0].time_s, c.start_s, abs_tol=1e-9, rel_tol=0)
        and math.isclose(rows[-1].time_s, c.end_s, abs_tol=1e-9, rel_tol=0)
        and all(b.time_s - a.time_s <= c.max_sample_gap_s + 1e-9 for a, b in zip(rows, rows[1:]))
    )
    if not complete:
        report["reason"] = "incomplete_or_gapped_window"
        return report
    for proxy in c.proxies:
        radius = proxy.protected_radius_m + c.robot_base_radius_m
        intervals = []
        clearance = math.inf
        for a, b in zip(rows, rows[1:]):
            clearance = min(
                clearance, _segment_distance(a.base_xy_m, b.base_xy_m, proxy.center_xy_m) - radius
            )
            hit = _segment_exposure(a.base_xy_m, b.base_xy_m, proxy.center_xy_m, radius)
            if hit is None:
                continue
            t0, t1 = (a.time_s + t * (b.time_s - a.time_s) for t in hit)
            if (
                intervals
                and abs(intervals[-1][1] - t0) <= 1e-9
                and math.dist(a.base_xy_m, proxy.center_xy_m) < radius
            ):
                intervals[-1][1] = t1
            else:
                intervals.append([t0, t1])
        duration = sum(b - a for a, b in intervals)
        longest = max((b - a for a, b in intervals), default=0.0)
        report["zones"].append(
            {
                "proxy_id": proxy.id,
                "min_clearance_m": clearance,
                "exposure_duration_s": duration,
                "longest_continuous_exposure_s": longest,
                "intervals_s": intervals,
                "sustained_exposure": longest + 1e-9 >= c.min_continuous_exposure_s,
            }
        )
    report.update(
        measurement_status="AVAILABLE",
        diagnostic_status="EXPOSURE_DETECTED"
        if any(z["sustained_exposure"] for z in report["zones"])
        else "NOT_DETECTED",
    )
    return report
