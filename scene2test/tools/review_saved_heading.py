"""Append a separate derived report; never rewrite original experiment evidence."""

import argparse
import json
from pathlib import Path

import numpy as np

from simulation_server.path_tracking import path_errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("job", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    request = json.loads((args.job / "request.json").read_text())
    old = json.loads((args.job / "execution_result.json").read_text())
    rows = [json.loads(line) for line in (args.job / "state_trajectory.jsonl").open()]
    spawn = next(
        (
            op["parameters"]
            for op in request["interventions"]
            if op["kind"] == "robot_initial_state.set_spawn"
        ),
        {},
    )
    origin = spawn.get("position_m", rows[0]["qpos"][:3])
    quat = spawn.get("quaternion_wxyz", rows[0]["qpos"][3:7])
    _, initial_heading = path_errors(origin, quat, origin, 0)
    errors = [path_errors(r["qpos"][:3], r["qpos"][3:7], origin, initial_heading) for r in rows]
    command = request["task"]["parameters"]
    eligible = not command.get("yaw_rate", 0) and not command.get("linear_velocity_y", 0)
    rates = np.array([r["qvel"][5] for r in rows if r["time_s"] >= 1])
    result = {
        "source_job": str(args.job),
        "derived_metrics_version": "2.0",
        "yaw_rate_rmse_radps": float(np.sqrt(np.mean((rates - command.get("yaw_rate", 0)) ** 2)))
        if len(rates)
        else None,
        "straight_path_applicable": bool(eligible),
        "maximum_cross_track_m": max(abs(e[0]) for e in errors),
        "maximum_heading_error_rad": max(abs(e[1]) for e in errors),
        "execution_valid": old["execution"]["valid"]
        and old["execution"]["termination_reason"] != "NUMERICAL_INSTABILITY",
        "notes": "Fixed-command replay only; slip requires model/contact reconstruction. "
        "Original evidence and Client verdicts are unchanged.",
    }
    result["straight_path_success"] = bool(
        eligible
        and result["execution_valid"]
        and old["task_facts"].get("standing_at_end")
        and result["maximum_cross_track_m"] <= 0.2
        and result["maximum_heading_error_rad"] <= 0.2
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
