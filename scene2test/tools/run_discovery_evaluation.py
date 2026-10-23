"""Initialize/resume a frozen seed-isolated AFS evaluation. No implicit live execution."""

import argparse
import json
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.independent_discovery import DiscoveryEvaluation
from robot_vlm.debug_log import clean


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["init", "run", "status", "report"])
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--max-new-attempts", type=int)
    parser.add_argument("--max-new-afs-requests", type=int)
    parser.add_argument("--continue-after-exclusion", action="store_true")
    args = parser.parse_args(argv)
    if args.op != "run" and (
        args.live
        or args.max_new_attempts is not None
        or args.continue_after_exclusion
        or args.max_new_afs_requests is not None
    ):
        parser.error("execution flags belong to run only")
    if (args.op == "init") != (args.manifest is not None):
        parser.error("init requires manifest; other commands use the campaign's frozen manifest")
    if args.op == "init":
        DiscoveryEvaluation.create(args.campaign, read_json(args.manifest))
    engine = DiscoveryEvaluation(
        args.campaign,
        on_event=lambda e: print("EVALUATION_EVENT=" + json.dumps(e), flush=True),
    )
    if args.op == "run":
        try:
            engine.run(
                live=args.live,
                max_new_attempts=args.max_new_attempts,
                continue_after_exclusion=args.continue_after_exclusion,
                max_new_afs_requests=args.max_new_afs_requests,
            )
        except Exception as exc:
            print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}", flush=True)
            print("REPORT=" + str(engine.report()), flush=True)
            return 2
    if args.op in {"run", "report"}:
        print("REPORT=" + str(engine.report()), flush=True)
    result = engine.summary()
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if result["status"] in {"READY", "COMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
