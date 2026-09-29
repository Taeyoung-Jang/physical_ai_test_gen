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
    parser.add_argument(
        "--with-taxonomy",
        action="store_true",
        help="opt-in evidence-backed temporal association rules",
    )
    parser.add_argument(
        "--with-memory", action="store_true", help="P1 time evidence and case export"
    )
    parser.add_argument(
        "--bundle-video", action="store_true", help="copy MP4; requires --with-memory"
    )
    args = parser.parse_args(argv)
    if args.bundle_video and not args.with_memory:
        parser.error("--bundle-video requires --with-memory")
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
        rules = None
        if args.with_taxonomy:
            from failure_client.evaluation.failure_taxonomy import RULES, classify_record

            records = [classify_record(r) for r in records]
            rules = RULES
        metrics = calculate_discovery_metrics(records, config.design, family_rules=rules)
        memory = None
        if args.with_memory:
            from failure_client.archive.regression_cases import build_failure_memory

            memory = build_failure_memory(records)
        output = args.output_dir or Path("/workspace/g1_failure/runtime/failure_measures") / stamp
        report = write_discovery_report(
            output,
            config.campaign_id,
            records,
            metrics,
            memory=memory,
            include_video=args.bundle_video,
        )
    except (ValueError, OSError, TypeError, KeyError) as exc:
        parser.exit(2, f"Measurement stopped: {type(exc).__name__}: {exc}\n")
    valid = sum(g["valid_rollouts"] for g in metrics["groups"])
    excluded = sum(g["excluded_rollouts"] for g in metrics["groups"])
    print(f"FAILURE_MEASURES={report.parent}")
    print(f"REPORT={report}; valid={valid}; excluded={excluded}")
    print(f"COMPARISON={metrics['comparison']['status']}; family rules={list(rules or {})}")
    if memory is not None:
        print(
            f"MEMORY={report.parent / 'memory/index.html'}; cases={len(memory['cases'])}; "
            f"brackets={len(memory['brackets'])}"
        )


if __name__ == "__main__":
    main()
