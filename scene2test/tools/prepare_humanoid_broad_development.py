"""Prepare width-stratified full-range development plans offline; never execute robots."""

import argparse
import json
from pathlib import Path

from clear_path.fixture import initial_goal_relation
from clear_path.scene_space import axes_for_schema, scene_from_parameters
from clear_path.search_domain import check_parameters
from failure_client.experiments.paired_discovery import PairedDesign, paired_plan
from failure_client.methods.behavior_feedback import uniform_scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", required=True)
    args = parser.parse_args()
    base = json.loads(
        (Path(__file__).resolve().parents[1] / "config/random_environment_luna.json").read_text()
    )
    schema = "clear-path-human-v5"
    physical = axes_for_schema(schema)
    plans = []
    samples = []
    # Fixed numeric thirds, chosen before any new robot outcomes. Their union is
    # the original full rectangle; the common boundaries have zero probability.
    for name, bounds, seed in (
        ("narrow", [1.6, 2.4], 62001),
        ("middle", [2.4, 3.2], 62002),
        ("wide", [3.2, 4.0], 62003),
    ):
        config = json.loads(json.dumps(base))
        config["seeds"] = [seed]
        config["scene_domain"] = {
            "schema_version": "bounded-scene-domain-v1",
            "scene_schema": schema,
            "scope": "Development difficulty audit, not held-out AFS superiority evaluation. "
            "Width thirds jointly restore the original full domain; all other axes retain "
            "original bounds. No geometry/outcome rejection or resampling.",
            "axes": {key: list(value) for key, value in physical.items()},
        }
        config["scene_domain"]["axes"]["corridor_width_m"] = bounds
        design = PairedDesign.model_validate(config)
        wrapped = paired_plan(args.run, design)
        robot = wrapped["manifest"]["robot_config"]
        if robot["scene_schema"] != schema:
            raise ValueError("human-v5 controls required")
        plans.append((name, config, wrapped))
        for index in range(design.attempts_per_arm):
            parameters = uniform_scene(
                seed, "paired-random-v1", index, schema=schema, domain=design.scene_domain
            )
            check_parameters(parameters, design.scene_domain)
            relation = initial_goal_relation(scene_from_parameters(parameters, schema))
            gap = relation["goal_to_box_distance_m"]
            samples.append(
                {
                    "stratum": name,
                    "seed": seed,
                    "index": index,
                    "parameters": parameters,
                    "initial_goal_relation": relation,
                    "whole_goal_disk_inside_box_endpoint_envelope_sufficient": gap + 0.25 <= 0.4,
                }
            )
    # Validate and hash every plan before creating a new destination.
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for name, config, wrapped in plans:
        for suffix, data in (("config", config), ("plan", wrapped)):
            (args.output_dir / f"{name}_{suffix}.json").write_text(
                json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
            )
    audit = {
        "purpose": "development-only; no robot/API execution or observed outcomes",
        "strata": [name for name, _, _ in plans],
        "original_full_domain_union": True,
        "valid_target_total": 12,
        "attempt_cap_total": 12,
        "robot_policy_call_upper_bound": sum(
            wrapped["manifest"]["robot_api_call_upper_bound"] for _, _, wrapped in plans
        ),
        "afs_request_upper_bound": 0,
        "rejected_or_resampled": 0,
        "geometry_claim": "Initial box projection only; endpoint envelope uses the existing "
        "0.4m checker radius and 0.25m task radius. This is not physical impossibility, "
        "a path test, a failure verdict, or a complete geometry audit.",
        "planned_draws": samples,
    }
    (args.output_dir / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({key: value for key, value in audit.items() if key != "planned_draws"}))
    for name, _, _ in plans:
        rows = [row for row in samples if row["stratum"] == name]
        print(
            name,
            "whole-goal endpoint-envelope certificates:",
            sum(row["whole_goal_disk_inside_box_endpoint_envelope_sufficient"] for row in rows),
            "/",
            len(rows),
        )


if __name__ == "__main__":
    main()
