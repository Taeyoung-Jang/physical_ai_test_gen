"""Prepare behavior evidence; --live proposes scenes only, NEVER launches a robot."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

from llm_afs import behavior as b


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--history-run", type=Path, action="append", default=[])
    p.add_argument("--prior-suite", type=Path, action="append", default=[])
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true")
    mode.add_argument("--proposal", type=Path)
    mode.add_argument(
        "--recover-run", type=Path, help="reuse a legacy missing-hash response; no API"
    )
    mode.add_argument("--offline-demo", action="store_true")
    p.add_argument("--model", default="gpt-6-astra")
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--repeats", type=int, default=2, help="explicit repeat slots (1..4)")
    p.add_argument("--exploration", type=int, default=2, help="independent scene slots (1..8)")
    p.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/behavior_afs")
    )
    args = p.parse_args()
    if not 1 <= args.repeats <= 4 or not 1 <= args.exploration <= 8:
        p.error("repeats 1..4 and exploration 1..8 required")
    from llm_afs import provider

    ctx = b.context(b.summarize(args.run), [b.summarize(r) for r in args.history_run])
    from llm_afs.behavior_request import recover_legacy, request

    body = request(ctx, args.model)
    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"BEHAVIOR_AFS_RUN={root}", flush=True)
    b.write(root / "context.json", ctx)
    b.write(root / "request.json", body)
    raw, origin = None, "prepare_only"
    try:
        if args.live or args.proposal or args.recover_run or args.offline_demo:
            b.require_anchor(ctx["latest"])  # fail before a paid call on incompatible evidence
        if args.live:
            response = provider.call(body)
            b.write(root / "response.json", response)
            raw, origin = provider.extract_proposal(response), "openai_api"
        elif args.recover_run:
            raw, audit = recover_legacy(args.recover_run, ctx)
            b.write(root / "recovery.json", audit)
            origin = "recovered_openai_response"
        elif args.proposal:
            raw, origin = b.read(args.proposal), "imported_proposal"
        elif args.offline_demo:
            params = ctx["latest"]["parameters"]
            raw = {
                "context_sha256": b.digest(ctx),
                "spaces": [
                    {
                        "mode": mode,
                        "axis": axis,
                        "low": (b.AXES[axis][0] + params[axis]) / 2,
                        "high": (params[axis] + b.AXES[axis][1]) / 2,
                        "evidence_refs": ["outcome", "phase_metrics"],
                        "hypothesis": "OFFLINE wiring fixture, not LLM reasoning",
                        "alternative": "Controller/strategy may dominate instead of this axis",
                        "falsification": "Compare task outcome and recorded skill/phase metrics",
                    }
                    for mode, axis in [
                        ("boundary_probe", "box_mass_kg"),
                        ("cross_mechanism", "floor_friction"),
                    ]
                ],
            }
            origin = "offline_fixture"
        if raw is not None:
            b.write(root / "proposal.json", raw)
            suite = b.compile_suite(
                ctx,
                b.Proposal.model_validate(raw),
                root,
                seed=args.seed,
                prior_suites=[b.read(s) for s in args.prior_suite],
                repeats=args.repeats,
                exploration=args.exploration,
            )
            print(f"SUITE={root / 'suite.json'}; ready={suite['ready']}; origin={origin}")
        b.write(root / "status.json", {"origin": origin, "robot_launched": False})
    except Exception as exc:
        # Provider deliberately redacts credentials; keep validation failures visible.
        b.write(
            root / "error.json",
            {"type": type(exc).__name__, "message": str(exc), "robot_launched": False},
        )
        raise


if __name__ == "__main__":
    main()
