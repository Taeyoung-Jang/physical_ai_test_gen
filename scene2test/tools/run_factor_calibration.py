"""Offline preparation and bounded, opt-in live environment calibration (no AFS)."""

import argparse
import json
from pathlib import Path

from failure_client.experiments.afs_contrast import factor_plan
from failure_client.experiments.behavior_regression import BehaviorRegression
from failure_client.experiments.local_goal_adapter import LocalGoalRunner, atomic_json
from robot_vlm.debug_log import clean

ROOT = Path("/workspace/g1_failure/runtime/factor_calibration/luna_oat_20261021_v1")
BASE = Path("/workspace/g1_failure/runtime/behavior_regression/luna_success_control_20261021_v1")
# Predeclared levels, not selected using new experiment outcomes.
PROBES = [
    {"axis": "corridor_width_m", "value": 2.8},
    {"axis": "floor_friction", "value": 0.5},
    {"axis": "human_lateral_fraction", "value": -0.8},
]


def logged_runner(cfg, directory, params):
    print(
        "CALIBRATION_START=" + json.dumps({"attempt": directory.name, "scene": params}), flush=True
    )
    receipt = LocalGoalRunner()(cfg, directory, params)
    print("CALIBRATION_COLLECT=" + directory.name, flush=True)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="op", required=True)
    for op in ("plan", "init", "run", "status", "report"):
        p = sub.add_parser(op)
        p.add_argument("--suite", type=Path, default=ROOT)
        if op in {"plan", "init"}:
            p.add_argument("--run", type=Path, action="append")
        if op == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--max-new-attempts", type=int, default=8)
            p.add_argument("--continue-after-exclusion", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.op in {"plan", "init"}:
            paths = args.run or [
                BASE / "attempts" / f"attempt_{i:05d}" / "rollout" for i in range(2)
            ]
            plan = factor_plan(paths, probes=PROBES, repeats=2)
            if args.op == "plan":
                print(json.dumps(plan, ensure_ascii=False, indent=2))
                return 0
            BehaviorRegression.create(args.suite, plan)
            atomic_json(args.suite / "factor_plan.json", plan)
        engine = BehaviorRegression(args.suite, runner=logged_runner)
        if engine.state["lock"]["plan"].get("design") != "one-factor-at-a-time-v1":
            raise ValueError("not a factor calibration suite")
        if args.op == "run":
            print(
                "Fixed budget: 8 episodes / at most 80 robot policy calls / 0 AFS; "
                "stop on exclusion",
                flush=True,
            )
            engine.run(
                live=args.live,
                max_new_attempts=args.max_new_attempts,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        print(f"REPORT={engine.report()}")
        summary = engine.summary()
        summary["afs_requests"] = 0
        print("SUMMARY=" + json.dumps(summary, ensure_ascii=False))
        return 2 if summary["status"] == "NEEDS_ATTENTION" else 0
    except Exception as exc:
        print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
