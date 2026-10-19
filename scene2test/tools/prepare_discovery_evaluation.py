"""Read-only readiness/design preparation; optional new immutable manifest, no live run."""

import argparse
import json
from pathlib import Path

from failure_client.evaluation.discovery_readiness import audit_discovery
from failure_client.evaluation.goal_run_reader import read_goal_run, read_json
from failure_client.evaluation.research_records import RunInput
from failure_client.evaluation.taxonomy_profiles import classify_for_search
from failure_client.experiments.discovery_evaluation import EvaluationDesign, evaluation_plan
from failure_client.experiments.local_goal_adapter import atomic_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["audit", "plan", "freeze"])
    parser.add_argument("--schema", default="clear-path-human-v5")
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.op != "freeze" and args.output_dir:
        parser.error("output-dir belongs to explicit freeze only")
    try:
        if args.op == "audit":
            if args.config:
                parser.error("audit does not take evaluation config")
            records = [
                classify_for_search(
                    read_goal_run(RunInput(path=str(p.resolve()))), args.schema, "expanded-ten-v1"
                )
                for p in args.run
            ]
            result = audit_discovery(args.schema, records)
        else:
            if not args.config or not args.run:
                parser.error("plan/freeze require config and reviewed robot-control archives")
            result = evaluation_plan(
                args.run, EvaluationDesign.model_validate(read_json(args.config))
            )
            if args.op == "freeze":
                if not args.output_dir:
                    parser.error("freeze requires a NEW output-dir")
                output = args.output_dir.resolve()
                if any(
                    output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output)
                    for p in args.run
                ):
                    raise ValueError("output overlaps source evidence")
                output.mkdir(parents=True, exist_ok=False)
                atomic_json(output / "manifest.json", result)
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        print("No API/robot executed; evaluation history is empty; no goal/type verdicts assigned.")
        return 0
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Preparation stopped: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
