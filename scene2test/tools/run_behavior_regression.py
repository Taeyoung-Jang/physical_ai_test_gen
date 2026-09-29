"""Plan, initialize and explicitly execute fixed-budget saved-case regressions."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from failure_client.experiments.behavior_regression import (
    BehaviorRegression,
    memory_paths,
    replay_plan,
)
from robot_vlm.debug_log import clean


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("plan", "init"):
        sub = commands.add_parser(name, help="offline; no API/GPU execution")
        source = sub.add_mutually_exclusive_group(required=True)
        source.add_argument("--run", type=Path, action="append")
        source.add_argument(
            "--memory", type=Path, help="memory.json index; original archives must exist"
        )
        sub.add_argument("--repeats", type=int, default=2)
        sub.add_argument(
            "--model", help="explicit version comparison override; otherwise retain source model"
        )
        sub.add_argument("--groot-root", type=Path)
        if name == "init":
            sub.add_argument("--output-dir", type=Path)
    for name in ("run", "status", "report", "resolve"):
        sub = commands.add_parser(name)
        sub.add_argument("--suite", type=Path, required=True)
        if name == "run":
            sub.add_argument("--live", action="store_true")
            sub.add_argument("--max-new-attempts", type=int)
            sub.add_argument("--continue-after-exclusion", action="store_true")
        if name == "resolve":
            sub.add_argument("--exclude-pending", action="store_true", required=True)
            sub.add_argument("--note", required=True, help="confirm inspection and no active child")
    args = parser.parse_args(argv)
    try:
        if args.operation in {"plan", "init"}:
            paths = memory_paths(args.memory) if args.memory else args.run
            plan = replay_plan(
                paths, repeats=args.repeats, model=args.model, groot_root=args.groot_root
            )
            display = {k: v for k, v in plan.items() if k != "cases"}
            display["cases"] = [
                {k: c[k] for k in ("case_id", "baseline_role", "scene")}
                | {"target_robot": c["target_config"]["robot"]}
                for c in plan["cases"]
            ]
            print("REGRESSION_PLAN=" + json.dumps(display, ensure_ascii=False))
            if args.operation == "init":
                stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
                root = (
                    args.output_dir
                    or Path("/workspace/g1_failure/runtime/behavior_regression") / stamp
                )
                BehaviorRegression.create(root, plan)
                print(f"REGRESSION_SUITE={root.resolve()}; no robot launched")
            return
        suite = BehaviorRegression(args.suite)
        if args.operation == "run":
            suite.run(
                live=args.live,
                max_new_attempts=args.max_new_attempts,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        elif args.operation == "resolve":
            suite.exclude_pending(note=args.note)
        if args.operation in {"run", "report"}:
            print(f"REPORT={suite.report()}")
        print(json.dumps(suite.summary(), indent=2, ensure_ascii=False))
        if suite.state["status"] in {"NEEDS_ATTENTION", "COMPLETE_WITH_EXCLUSIONS"}:
            return 2
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        parser.exit(
            2, f"Regression stopped: {type(exc).__name__}: {clean(exc)}\nNo automatic retry.\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
