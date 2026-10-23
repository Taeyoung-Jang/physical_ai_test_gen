"""Approved three-case regression: at most six attempts/60 robot calls, no AFS calls."""

import argparse
import json
import os
from pathlib import Path

from failure_client.experiments.behavior_regression import BehaviorRegression, replay_plan
from robot_vlm.debug_log import clean

RUNTIME = Path("/workspace/g1_failure/runtime")
BASELINES = [
    RUNTIME
    / "afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout",
    RUNTIME / "trajectory_feedback/20261019T134446_66195/afs/attempts/attempt_00000/rollout",
    RUNTIME / "trajectory_feedback/20261019T134446_66195/afs/attempts/attempt_00005/rollout",
]
DEFAULT_SUITE = RUNTIME / "behavior_regression/sol_flex_20261020_v1"


def checked_plan(plan):
    if (
        plan["max_attempts"],
        plan["robot_api_call_upper_bound"],
        plan["afs_requests"],
        plan["attempts_per_case"],
    ) != (6, 60, 0, 2):
        raise ValueError("approved regression budget changed")
    if len(plan["cases"]) != 3:
        raise ValueError("exactly three approved cases required")
    sources = {
        str(Path(r["source"]["path"]).resolve()) for c in plan["cases"] for r in c["baselines"]
    }
    if sources != {str(p.resolve()) for p in BASELINES}:
        raise ValueError("approved baseline set changed")
    for case in plan["cases"]:
        robot = case["target_config"]["robot"]
        if (robot["model"], robot.get("service_tier"), robot["max_calls"]) != (
            "gpt-6.1-sol",
            "flex",
            10,
        ):
            raise ValueError("approved model/tier/call budget changed")
    return plan


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "operation", choices=["plan", "init", "run", "status", "report"], default="plan", nargs="?"
    )
    p.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    p.add_argument("--live", action="store_true")
    args = p.parse_args(argv)
    if args.live and args.operation != "run":
        p.error("--live belongs to run only")
    try:
        if args.operation in {"plan", "init"}:
            plan = checked_plan(
                replay_plan(BASELINES, repeats=2, model="gpt-6.1-sol", service_tier="flex")
            )
            print(
                "PLAN="
                + json.dumps(
                    {
                        "cases": [
                            {"case_id": c["case_id"], "baseline_role": c["baseline_role"]}
                            for c in plan["cases"]
                        ],
                        "model": "gpt-6.1-sol",
                        "service_tier": "flex",
                        "max_attempts": 6,
                        "robot_api_call_upper_bound": 60,
                        "afs_requests": 0,
                        "http_read_timeout_s": 300,
                        "no_automatic_episode_retry": True,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            if args.operation == "init":
                BehaviorRegression.create(args.suite, plan)
                print(f"SUITE={args.suite.resolve()}; no API or robot launched")
            return 0
        suite = BehaviorRegression(args.suite)
        checked_plan(suite.state["lock"]["plan"])
        if args.operation == "run":
            if not args.live or not os.environ.get("OPENAI_API_KEY", "").strip():
                raise ValueError(
                    "run requires --live and OPENAI_API_KEY in the execution environment"
                )
            suite.run(live=True, max_new_attempts=6)
        if args.operation in {"run", "report"}:
            print(f"REPORT={suite.report()}", flush=True)
        print("SUMMARY=" + json.dumps(suite.summary(), ensure_ascii=False), flush=True)
        return 2 if suite.state["status"] in {"NEEDS_ATTENTION", "COMPLETE_WITH_EXCLUSIONS"} else 0
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}; no automatic retry", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
