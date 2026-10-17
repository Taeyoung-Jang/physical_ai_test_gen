"""One bounded development search, with explicit historical evidence and live opt-in."""

import argparse
import json
import os
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.afs_autonomous import AutonomousAFS, development_plan, stamp
from failure_client.methods.autonomous_feedback import SearchBudget
from robot_vlm.debug_log import clean

RUNTIME = Path("/workspace/g1_failure/runtime/afs_autonomous")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["plan", "init", "run", "status", "report"])
    parser.add_argument(
        "--run", type=Path, action="append", help="reviewed archive; repeat in observation order"
    )
    parser.add_argument(
        "--session", type=Path, help="resume existing session without changing its budget"
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--config", type=Path, help="new session SearchBudget JSON; robot settings are inherited"
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument(
        "--max-new-attempts",
        type=int,
        help="optional invocation limit; default runs remaining budget",
    )
    parser.add_argument("--continue-after-exclusion", action="store_true")
    args = parser.parse_args(argv)
    if args.session and (args.run or args.config or args.output_dir):
        parser.error("resume cannot replace history, output or frozen configuration")
    if args.op in {"status", "report"} and not args.session:
        parser.error("status/report require --session")
    if args.op in {"plan", "init"} and args.session:
        parser.error("plan/init require new history, not an existing session")
    if not args.session and not args.run:
        parser.error("new sessions require explicit --run archive arguments")
    if args.op != "run" and (
        args.live or args.max_new_attempts is not None or args.continue_after_exclusion
    ):
        parser.error("execution flags belong to run only")
    if args.op == "run" and not args.live:
        parser.error("run requires --live; use plan or init for offline preparation")
    if args.max_new_attempts is not None and args.max_new_attempts < 0:
        parser.error("--max-new-attempts must be nonnegative")
    engine = None
    try:
        if args.op == "run" and not os.getenv("OPENAI_API_KEY"):
            raise ValueError(
                "set OPENAI_API_KEY in this terminal; no key is saved in configuration"
            )
        if args.session:
            engine = AutonomousAFS(args.session)
        else:
            budget = (
                SearchBudget.model_validate(read_json(args.config))
                if args.config
                else SearchBudget()
            )
            if args.op == "plan":
                plan = development_plan(args.run, budget)["plan"]
                print(
                    "AUTONOMOUS_PLAN="
                    + json.dumps(
                        {k: v for k, v in plan.items() if k != "history"}, ensure_ascii=False
                    )
                )
                print("No API, robot or output directory created.")
                return 0
            root = AutonomousAFS.create(args.output_dir or RUNTIME / stamp(), args.run, budget)
            engine = AutonomousAFS(root)
        print(f"AFS_AUTONOMOUS={engine.root}", flush=True)
        engine.on_event = lambda event: print(
            "AUTONOMOUS_EVENT=" + json.dumps(event, ensure_ascii=False), flush=True
        )
        if args.op == "run":
            engine.run(
                live=True,
                max_new_attempts=args.max_new_attempts,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        if args.op != "status":
            print(f"REPORT={engine.report()}", flush=True)
        print("AUTONOMOUS_SUMMARY=" + json.dumps(engine.summary(), ensure_ascii=False))
        return 2 if engine.state["status"] == "NEEDS_ATTENTION" else 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}", flush=True)
        if engine is not None:
            print(f"EVIDENCE={engine.root}; no ambiguous request will be resent", flush=True)
            try:
                print(f"REPORT={engine.report()}", flush=True)
            except Exception as report_error:
                print(f"REPORT_ERROR={type(report_error).__name__}: {clean(str(report_error))}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
