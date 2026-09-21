"""Robot-side camera policy. Mock by default; --live explicitly enables paid calls."""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--model", default="gpt-6-astra")
    p.add_argument("--max-calls", type=int, default=10)
    p.add_argument("--max-seconds", type=float, default=30)
    p.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    p.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/robot_vlm")
    )
    args = p.parse_args()
    if not 1 <= args.max_calls <= 20 or not 3 <= args.max_seconds <= 120:
        p.error("max-calls 1..20 and max-seconds 3..120 required")
    if args.live and not os.getenv("OPENAI_API_KEY"):
        p.error("set OPENAI_API_KEY locally; do not put it in command arguments")
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ["SIM_SERVER_ONNX_PROVIDER"] = "cuda"
    from robot_vlm.policy import MockPolicy, OpenAIPolicy
    from robot_vlm.runner import run, write

    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"ROBOT_VLM_RUN={root}", flush=True)
    policy = OpenAIPolicy(model=args.model) if args.live else MockPolicy()
    try:
        result = run(
            root, args.groot_root, policy, max_calls=args.max_calls, max_seconds=args.max_seconds
        )
    except Exception as exc:
        write(
            root / "error.json",
            {"type": type(exc).__name__, "stage": "robot_loop", "valid_execution": False},
        )
        raise SystemExit("robot loop error; artifacts preserved (details redacted)") from None
    print(f"REPORT={root / 'report.html'}; reason={result['reason']}", flush=True)


if __name__ == "__main__":
    main()
