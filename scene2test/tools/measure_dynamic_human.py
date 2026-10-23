"""Read-only dynamic safety measurement; write results only to a new destination."""

import argparse
import json
from pathlib import Path

from failure_client.evaluation.dynamic_human_safety import measure_dynamic_humans
from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import RunInput


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.resolve().is_relative_to(args.run.resolve()):
        parser.error("destination must be outside original archive")
    record = read_goal_run(RunInput(path=str(args.run.resolve())))
    result = measure_dynamic_humans(record)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "measurement.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in {"evidence", "exposure_intervals_s"}}
        )
    )


if __name__ == "__main__":
    main()
