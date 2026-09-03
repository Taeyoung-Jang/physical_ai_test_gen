#!/usr/bin/env python3
"""Materialize and optionally run a reproducible locomotion command sweep."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

DEFAULT_OUTPUT_ROOT = Path("/workspace/g1_failure/runtime/protocols")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sweep", type=Path, default=Path("config/locomotion_command_sweep.yaml"))
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--server-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--client-workspace", type=Path, default=Path("/workspace/g1_failure/runtime/client")
    )
    return parser.parse_args()


def _protocol(base: dict, sweep: dict, command: dict) -> dict:
    protocol = yaml.safe_load(yaml.safe_dump(base))
    command_id = command["id"]
    protocol["experiment"] = {
        "experiment_id": f"{sweep['experiment_prefix']}_{command_id}",
        "title": f"G1 locomotion command sweep: {command_id}",
        "research_question": "Does the GPU walking policy remain upright and track this command?",
        "hypothesis": "The robot remains upright and velocity RMSE stays within tolerance.",
    }
    task = {key: value for key, value in command.items() if key != "id"}
    task["minimum_forward_distance_m"] = 0.0
    task["velocity_rmse_tolerance"] = sweep["velocity_rmse_tolerance"]
    protocol["task"]["parameters"] = task
    protocol["execution"]["repeats_per_candidate"] = sweep["repeats_per_command"]
    protocol["execution"]["master_seed"] = 20260903
    protocol["artifacts"]["video"] = sweep["video"]
    protocol["failure_definition"] = {
        "id": "g1_command_tracking_failure",
        "version": "1.0",
        "config": {
            "failure_events": [
                {
                    "rule_id": "base_height_threshold_crossed",
                    "event_type": "BASE_HEIGHT_THRESHOLD_CROSSED",
                }
            ],
            "success_predicates": [
                {
                    "rule_id": "standing_at_end",
                    "source": "task_facts",
                    "path": "standing_at_end",
                    "operator": "truthy",
                },
                {
                    "rule_id": "command_tracking_success",
                    "source": "task_facts",
                    "path": "command_tracking_success",
                    "operator": "truthy",
                },
            ],
        },
    }
    return protocol


def main() -> None:
    args = _arguments()
    sweep = yaml.safe_load(args.sweep.read_text(encoding="utf-8"))
    base_path = Path(sweep["base_protocol"])
    base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
    output_dir = args.output_root / sweep["experiment_prefix"]
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "FAILURE_CLIENT_SERVER_URL": args.server_url,
            "FAILURE_CLIENT_WORKSPACE": str(args.client_workspace),
            "FAILURE_CLIENT_TIMEOUT_S": "180",
            "FAILURE_CLIENT_MAX_ATTEMPTS": "3",
        }
    )
    for command in sweep["commands"]:
        protocol = _protocol(base, sweep, command)
        path = output_dir / f"{command['id']}.yaml"
        path.write_text(
            yaml.safe_dump(protocol, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        print(f"materialized {path}", flush=True)
        if args.run:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "failure_client.cli",
                    "run",
                    str(path),
                    "--poll-interval",
                    "0.5",
                ],
                check=True,
                env=environment,
            )


if __name__ == "__main__":
    main()
