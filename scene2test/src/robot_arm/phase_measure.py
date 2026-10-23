"""Descriptive object-motion observations, never grasp-state or causal family labels."""

import json
import math
from pathlib import Path

from robot_arm import capability

CONTRACT = {
    "version": "object-motion-observation-v1",
    "settle_s": 1.0,
    "rise_m": 0.03,
    "movement_m": 0.05,
    "near_goal_center_xy_m": 0.05,
    "little_motion_m": 0.02,
}


def case_measure(directory, receipt):
    base = capability.case_measure(directory, receipt)
    base["motion_contract"] = CONTRACT
    if base["status"] != "COMPLETE":
        base["motion_observations"] = {"status": "UNKNOWN", "pattern": None}
        return base
    rows = [json.loads(s) for s in (Path(directory) / "physics.jsonl").read_text().splitlines()]
    selected = [r for r in rows if r["time_s"] - rows[0]["time_s"] >= CONTRACT["settle_s"]]
    if not selected:
        base["motion_observations"] = {
            "status": "UNKNOWN",
            "pattern": None,
            "reason": "episode_shorter_than_settle_window",
        }
        return base
    anchor = selected[0]["bowl_xyz_m"]
    rise = max(r["bowl_xyz_m"][2] - anchor[2] for r in selected)
    movement = max(math.dist(r["bowl_xyz_m"][:2], anchor[:2]) for r in selected)
    gap = min(math.dist(r["bowl_xyz_m"][:2], r["plate_xyz_m"][:2]) for r in selected)
    first_contact = next(
        (
            r["time_s"] - rows[0]["time_s"]
            for r in rows
            if any(
                e["kind"] in {"robot_obstacle", "bowl_obstacle"}
                and (
                    e["distance_m"] <= capability.CONTRACT["contact_distance_tolerance_m"]
                    or e["force_n"] > 0
                )
                for e in r["contacts"]
            )
        ),
        None,
    )
    if receipt["task_outcome"] == "PASS":
        pattern = "native_task_completed"
    elif rise < CONTRACT["little_motion_m"] and movement < CONTRACT["little_motion_m"]:
        pattern = "little_object_motion"
    elif gap <= CONTRACT["near_goal_center_xy_m"]:
        pattern = "object_near_goal_native_task_incomplete"
    else:
        pattern = "object_moved_native_task_incomplete"
    base["motion_observations"] = {
        "status": "COMPLETE",
        "pattern": pattern,
        "max_rise_after_settle_m": rise,
        "max_xy_movement_after_settle_m": movement,
        "min_goal_center_xy_gap_after_settle_m": gap,
        "first_obstacle_contact_elapsed_s": first_contact,
        "rise_ge_3cm": rise >= CONTRACT["rise_m"],
        "movement_ge_5cm": movement >= CONTRACT["movement_m"],
        "cause": "UNCONFIRMED",
        "claim": "Motion heuristics only; no confirmed grasp, drop, avoidance "
        "or causal failure type.",
    }
    return base
