"""Prepare an audited development continuation, or explicitly run one bounded step."""

import argparse
import json
from pathlib import Path

from failure_client.experiments.discovery_continuation import (
    DevelopmentContinuation,
    prepare_continuation,
)
from robot_vlm.debug_log import clean


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["prepare", "run", "status", "report"])
    parser.add_argument("--source", type=Path)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--continue-after-exclusion", action="store_true")
    parser.add_argument("--max-new-attempts", type=int, default=1)
    parser.add_argument("--max-new-afs-requests", type=int, default=1)
    args = parser.parse_args(argv)
    if args.op == "prepare":
        if not args.source or args.live or args.continue_after_exclusion:
            parser.error("prepare requires source, never live/continue flags")
        result = prepare_continuation(args.source, args.campaign, apply=args.apply)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print("No API/robot executed; source and consumed budgets preserved.")
        return 0
    if (
        args.source
        or args.apply
        or (args.op != "run" and (args.live or args.continue_after_exclusion))
    ):
        parser.error("source/apply belong to prepare; execution flags belong to run")
    engine = DevelopmentContinuation(
        args.campaign, on_event=lambda e: print("CONTINUATION_EVENT=" + json.dumps(e), flush=True)
    )
    if args.op == "run":
        try:
            engine.run(
                live=args.live,
                max_new_attempts=args.max_new_attempts,
                max_new_afs_requests=args.max_new_afs_requests,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        except Exception as exc:
            print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}")
            print("REPORT=" + str(engine.report()))
            return 2
    if args.op in {"run", "report"}:
        print("REPORT=" + str(engine.report()))
    result = engine.summary()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"READY", "COMPLETE"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
