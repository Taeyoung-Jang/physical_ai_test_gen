"""Observed task limits and separate contact/fall measures, never new task verdicts."""

import json
import math
from pathlib import Path

from robot_arm import obstacles, placement, search

CONTRACT = {
    "version": "arm-contact-fall-v1",
    "below_table_margin_m": 0.05,
    "below_table_dwell_s": 0.10,
    "contact_distance_tolerance_m": 1e-6,
}


def validate_suite(suite):
    search.validate(suite["experiment"])
    if suite["version"] != "arm-capability-suite-v1" or suite["measurement"] != CONTRACT:
        raise ValueError("unsupported capability measurement contract")
    cases = suite["cases"]
    if not 1 <= len(cases) <= 12 or len({c["id"] for c in cases}) != len(cases):
        raise ValueError("one to twelve uniquely named cases required")
    for case in cases:
        if not isinstance(case["id"], str) or not case["id"].replace("_", "").isalnum():
            raise ValueError("invalid case ID")
        placement.checked(case["positions"], suite["experiment"]["bounds"])
        obstacles.checked(case["obstacles"])
        if "line_t" in case and (
            type(case["line_t"]) not in (int, float)
            or not math.isfinite(case["line_t"])
            or not 0 <= case["line_t"] <= 1
        ):
            raise ValueError("line_t must be finite and within [0,1]")
        if type(case["scene_seed"]) is not int or not 0 <= case["scene_seed"] < 100000000:
            raise ValueError("invalid policy seed")
    return suite


def measure(rows, expected_duration=None):
    unknown = {"status": "UNKNOWN", "contact": None, "fell_below_table": None}
    if len(rows) < 2:
        return dict(unknown, reason="missing_or_partial_physics")
    try:
        dt = rows[0]["dt_s"]
        if not math.isfinite(dt) or dt <= 0:
            return dict(unknown, reason="invalid_timestep")
        for i, row in enumerate(rows):
            if (
                not all(
                    math.isfinite(float(x))
                    for key in ("bowl_xyz_m", "plate_xyz_m", "eef_xyz_m")
                    for x in row[key]
                )
                or not math.isfinite(row["time_s"])
                or not math.isfinite(row["table_surface_z_m"])
                or not isinstance(row["contacts"], list)
                or row["dt_s"] != dt
                or row["table_surface_z_m"] != rows[0]["table_surface_z_m"]
                or (i and abs(row["time_s"] - rows[i - 1]["time_s"] - dt) > 1e-7)
            ):
                return dict(unknown, reason="gapped_or_inconsistent_physics")
        duration = rows[-1]["time_s"] - rows[0]["time_s"]
        if expected_duration is not None and abs(duration - expected_duration) > dt * 0.1:
            return dict(unknown, reason="physics_control_duration_mismatch")
        seen = set()
        contact_time = {"robot_obstacle": 0.0, "bowl_obstacle": 0.0}
        peak = 0.0
        below = longest = 0.0
        min_gap = float("inf")
        for row in rows[1:]:
            active = set()
            for event in row["contacts"]:
                if (
                    not math.isfinite(event["force_n"])
                    or event["force_n"] < 0
                    or not math.isfinite(event["distance_m"])
                ):
                    return dict(unknown, reason="invalid_contact_record")
                if (
                    event["distance_m"] <= CONTRACT["contact_distance_tolerance_m"]
                    or event["force_n"] > 0
                ):
                    active.add(event["kind"])
                    peak = max(peak, event["force_n"])
            seen.update(active)
            for kind in contact_time:
                contact_time[kind] += dt if kind in active else 0
            gap = math.dist(row["bowl_xyz_m"][:2], row["plate_xyz_m"][:2])
            min_gap = min(gap, min_gap)
            z = row["bowl_xyz_m"][2]
            below = (
                below + dt if z < row["table_surface_z_m"] - CONTRACT["below_table_margin_m"] else 0
            )
            longest = max(longest, below)
        return {
            "status": "COMPLETE",
            "physics_samples": len(rows),
            "duration_s": duration,
            "contact": bool(seen & contact_time.keys()),
            "contact_kinds": sorted(seen),
            "contact_duration_s": contact_time,
            "peak_obstacle_force_n": peak,
            "fell_below_table": longest + 1e-9 >= CONTRACT["below_table_dwell_s"],
            "longest_below_table_s": longest,
            "min_bowl_plate_xy_distance_m": min_gap,
            "cause": "UNCONFIRMED",
            "claim": (
                "Observed contact/below-surface events only; "
                "grasp/drop/avoidance cause unconfirmed."
            ),
        }
    except (KeyError, TypeError, ValueError):
        return dict(unknown, reason="missing_or_invalid_fields")


def case_measure(directory, receipt):
    directory = Path(directory)
    physics = directory / "physics.jsonl"
    if receipt.get("status") != "VALID" or not physics.exists():
        return {
            "status": "UNKNOWN",
            "contact": None,
            "fell_below_table": None,
            "reason": "excluded_or_missing_physics",
        }
    try:
        rows = [json.loads(x) for x in physics.read_text().splitlines()]
    except (ValueError, OSError):
        return {
            "status": "UNKNOWN",
            "contact": None,
            "fell_below_table": None,
            "reason": "partial_or_invalid_physics",
        }
    expected = receipt["steps"][0] / 20  # Fixed LIBERO control frequency; verified in worker.
    return measure(rows, expected_duration=expected)


def brackets(cases, outcomes):
    points = [c for c in cases if "line_t" in c and not c["obstacles"]]
    points.sort(key=lambda c: c["line_t"])
    if not points:
        return {"status": "NO_CONTROLLED_LINE", "intervals": []}
    base = points[0]
    # Fixed start object, policy seed and plate path; only one predeclared line parameter changes.
    for c in points:
        if (
            c["positions"]["bowl_x"] != base["positions"]["bowl_x"]
            or c["positions"]["bowl_y"] != base["positions"]["bowl_y"]
            or c["scene_seed"] != base["scene_seed"]
        ):
            return {"status": "UNMATCHED_CONTROLS", "intervals": []}

    t0, t1 = points[0]["line_t"], points[-1]["line_t"]
    if (
        len(points) < 2
        or not all(type(c["line_t"]) in (int, float) and math.isfinite(c["line_t"]) for c in points)
        or t1 <= t0
    ):
        return {"status": "INVALID_LINE", "intervals": []}
    for c in points:
        fraction = (c["line_t"] - t0) / (t1 - t0)
        for axis in ("plate_x", "plate_y"):
            expected = points[0]["positions"][axis] + fraction * (
                points[-1]["positions"][axis] - points[0]["positions"][axis]
            )
            if abs(c["positions"][axis] - expected) > 1e-8:
                return {"status": "UNMATCHED_CONTROLS", "intervals": []}
    intervals = []
    observations = []
    for c in points:
        r = outcomes.get(c["id"], {})
        outcome = r.get("task_outcome") if r.get("status") == "VALID" else None
        observations.append({"case": c["id"], "line_t": c["line_t"], "outcome": outcome})
    for a, b in zip(observations, observations[1:]):
        if a["outcome"] and b["outcome"] and a["outcome"] != b["outcome"]:
            left = next(c for c in points if c["id"] == a["case"])
            right = next(c for c in points if c["id"] == b["case"])
            width = math.dist(
                [left["positions"]["plate_x"], left["positions"]["plate_y"]],
                [right["positions"]["plate_x"], right["positions"]["plate_y"]],
            )
            intervals.append(
                {
                    "left": a,
                    "right": b,
                    "plate_path_width_m": width,
                    "next_probe": {
                        "positions": {
                            k: (left["positions"][k] + right["positions"][k]) / 2
                            for k in placement.AXES
                        },
                        "scene_seed": base["scene_seed"],
                        "line_t": (a["line_t"] + b["line_t"]) / 2,
                        "execution": "not run; new budget/version required",
                    },
                }
            )
    return {
        "status": "OBSERVED_TRANSITION" if intervals else "NO_BRACKET_OBSERVED",
        "observations": observations,
        "intervals": intervals,
        "claim": (
            "Single-repeat task-success transitions; "
            "not kinematic reachability or monotonic success proof."
        ),
    }


def report(root):
    m = search.read(root / "manifest.json")
    suite = m["suite"]
    outcomes, results = {}, []
    for i, case in enumerate(suite["cases"]):
        d = root / f"attempt_{i:05d}"
        receipt = search.read(d / "receipt.json") if (d / "receipt.json").exists() else {}
        if receipt and not (d / "evidence_manifest.json").exists():
            receipt = {"status": "UNVERIFIED_PENDING_FINALIZATION", "task_outcome": None}
        outcomes[case["id"]] = receipt
        measurement = case_measure(d, receipt)
        results.append(
            {
                "case": case["id"],
                "task_outcome": receipt.get("task_outcome"),
                "execution_status": receipt.get("status", "NOT_COMPLETED"),
                "measurement": measurement,
                "video_directory": str(d / "videos"),
            }
        )
    contrasts = []
    for i, case in enumerate(suite["cases"]):
        control_id = case.get("control")
        if not control_id:
            continue
        control = next((c for c in suite["cases"] if c["id"] == control_id), None)
        matched = bool(
            control
            and control["positions"] == case["positions"]
            and control["scene_seed"] == case["scene_seed"]
            and not control["obstacles"]
        )
        contrasts.append(
            {
                "case": case["id"],
                "control": control_id,
                "matched": matched,
                "control_outcome": outcomes.get(control_id, {}).get("task_outcome"),
                "candidate_outcome": outcomes[case["id"]].get("task_outcome"),
                "cause": "UNCONFIRMED",
            }
        )
    return {
        "measurement_contract": CONTRACT,
        "cases": results,
        "task_boundary": brackets(suite["cases"], outcomes),
        "obstacle_contrasts": contrasts,
        "statistical_superiority_established": False,
        "note": "Development suite only. Original task outcomes unchanged; no superiority claim.",
    }
