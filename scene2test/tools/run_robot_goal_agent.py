"""Robot-side camera policy. Mock by default; --live explicitly enables paid calls."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--enable-push", action="store_true", help="experimental short physical push")
    p.add_argument("--model", default="gpt-6-astra")
    p.add_argument("--max-calls", type=int, default=10)
    p.add_argument("--max-seconds", type=float, default=120)
    p.add_argument(
        "--response-timeout",
        type=float,
        default=90,
        help="HTTP read timeout in seconds (1..300); runner deadline adds 30s",
    )
    p.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    p.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/robot_goal_agent")
    )
    args = p.parse_args()
    if not 1 <= args.max_calls <= 20 or not 3 <= args.max_seconds <= 120:
        p.error("max-calls 1..20 and max-seconds 3..120 required")
    from robot_vlm.timing import RequestTiming

    try:
        timing = RequestTiming(args.response_timeout)
    except ValueError as exc:
        p.error(str(exc))
    print(
        f"TIMING: HTTP read={timing.read_s}s; runner deadline={timing.deadline_s}s; "
        f"simulation={args.max_seconds}s (includes inference waits); automatic retries=0",
        flush=True,
    )
    if args.live and not os.getenv("OPENAI_API_KEY"):
        p.error("set OPENAI_API_KEY locally; do not put it in command arguments")
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ["SIM_SERVER_ONNX_PROVIDER"] = "cuda"
    from robot_vlm.debug_log import exception_detail
    from robot_vlm.goal_policy import GoalMock, GoalPolicy
    from robot_vlm.goal_runner import run, write

    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"ROBOT_GOAL_AGENT_RUN={root}", flush=True)
    if args.enable_push:
        from robot_vlm.push_policy import PushMock, PushPolicy

        policy = PushPolicy(model=args.model) if args.live else PushMock()
    else:
        policy = GoalPolicy(model=args.model) if args.live else GoalMock()
    try:
        result = run(
            root,
            args.groot_root,
            policy,
            max_calls=args.max_calls,
            max_seconds=args.max_seconds,
            enable_push=args.enable_push,
            response_timeout=timing.read_s,
        )
    except Exception as exc:
        write(
            root / "error.json",
            {
                "type": type(exc).__name__,
                "stage": "robot_loop",
                "valid_execution": False,
                "exception_chain": exception_detail(exc),
            },
        )
        raise SystemExit(
            "robot loop error; inspect error.json for redacted message and stack"
        ) from None
    print(
        f"DEBUG_LOGS={root / 'api_call_*.jsonl'}; per-call wall deadline={timing.deadline_s}s; "
        f"simulation budget={args.max_seconds}s",
        flush=True,
    )
    print(f"REPORT={root / 'report.html'}; reason={result['reason']}", flush=True)


if __name__ == "__main__":
    main()
