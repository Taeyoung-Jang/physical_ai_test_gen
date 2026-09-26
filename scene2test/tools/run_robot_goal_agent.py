"""Robot-side camera policy. Mock by default; --live explicitly enables paid calls."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--scene-config", type=Path, help="AFS scene JSON; environment fields only")
    p.add_argument("--enable-push", action="store_true", help="experimental short physical push")
    p.add_argument("--model", default="gpt-6-astra")
    p.add_argument("--max-calls", type=int, default=10)
    p.add_argument(
        "--evaluation-profile",
        choices=["goal_outcome_v1", "legacy_guarded"],
        default="goal_outcome_v1",
        help="default: evaluate only the original goal",
    )
    p.add_argument(
        "--max-seconds",
        type=float,
        default=None,
        help="optional simulation limit >=3 seconds; default: unlimited",
    )
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
    import json

    from robot_vlm.scene_config import validate_scene

    config = validate_scene(
        json.loads(args.scene_config.read_text()) if args.scene_config else None
    )
    if not 1 <= args.max_calls <= 20:
        p.error("max-calls 1..20 required")
    from robot_vlm.budget import simulation_limit

    try:
        simulation_limit(args.max_seconds)
    except ValueError as exc:
        p.error(str(exc))
    simulation_label = "unlimited" if args.max_seconds is None else f"{args.max_seconds}s"
    from robot_vlm.timing import RequestTiming

    try:
        timing = RequestTiming(args.response_timeout)
    except ValueError as exc:
        p.error(str(exc))
    print(
        f"TIMING: HTTP read={timing.read_s}s; runner deadline={timing.deadline_s}s; "
        f"simulation={simulation_label} (includes inference waits); automatic retries=0",
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
            scene_config=config.model_dump(),
            evaluation_profile=args.evaluation_profile,
        )
    except Exception as exc:
        write(
            root / "error.json",
            {
                "type": type(exc).__name__,
                "stage": "robot_loop",
                "valid_execution": False,
                "task_outcome": "INCONCLUSIVE",
                "evaluation_profile": args.evaluation_profile,
                "exception_chain": exception_detail(exc),
            },
        )
        raise SystemExit(
            "robot loop error; inspect error.json for redacted message and stack"
        ) from None
    print(
        f"DEBUG_LOGS={root / 'api_call_*.jsonl'}; per-call wall deadline={timing.deadline_s}s; "
        f"simulation budget={simulation_label}",
        flush=True,
    )
    print(
        f"REPORT={root / 'report.html'}; outcome={result['task_outcome']}; "
        f"reason={result['reason']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
