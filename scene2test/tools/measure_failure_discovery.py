"""Read saved goal-agent runs; measure without API/GPU calls or source modifications."""

import argparse
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_goal_run, read_json
from failure_client.evaluation.research_records import MeasurementInput, RunInput
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.reporting.discovery_report import write_discovery_report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--run", type=Path, action="append", help="repeat for independent saved runs"
    )
    source.add_argument(
        "--input", type=Path, help="versioned measurement-input JSON; no robot launch"
    )
    parser.add_argument("--output-dir", type=Path, help="new directory; refuses overwrites")
    args = parser.parse_args(argv)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    try:
        if args.input:
            config = MeasurementInput.model_validate(read_json(args.input))
            config.runs = [
                r.model_copy(update={"path": str((args.input.resolve().parent / r.path).resolve())})
                for r in config.runs
            ]
        else:
            config = MeasurementInput(
                campaign_id="inspection-" + stamp,
                runs=[RunInput(path=str(path.resolve())) for path in args.run],
            )
        records = [read_goal_run(r) for r in config.runs]
        metrics = calculate_discovery_metrics(records, config.design)
        output = args.output_dir or Path("/workspace/g1_failure/runtime/failure_measures") / stamp
        report = write_discovery_report(output, config.campaign_id, records, metrics)
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"Measurement stopped: {type(exc).__name__}: {exc}\n")
    valid = sum(g["valid_rollouts"] for g in metrics["groups"])
    excluded = sum(g["excluded_rollouts"] for g in metrics["groups"])
    print(f"FAILURE_MEASURES={report.parent}")
    print(f"REPORT={report}; valid={valid}; excluded={excluded}")
    print(f"COMPARISON={metrics['comparison']['status']}; family detectors=not implemented")


if __name__ == "__main__":
    main()
