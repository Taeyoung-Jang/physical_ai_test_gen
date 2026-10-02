"""Bounded development contrasts. Default commands do not launch API/GPU work."""

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from failure_client.experiments.afs_contrast import (
    MODE,
    contrast_plan,
    next_request,
    next_selection,
    selected_plan,
    write_preview,
)
from failure_client.experiments.behavior_regression import BehaviorRegression
from failure_client.experiments.local_goal_adapter import atomic_json
from robot_vlm.debug_log import clean

RUNTIME = Path("/workspace/g1_failure/runtime/afs_contrast")


def stamp():
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="op", required=True)
    p = subs.add_parser(
        "prepare-pair", help="offline: reviewed v4 success evidence, one AFS request"
    )
    p.add_argument(
        "--run",
        type=Path,
        action="append",
        required=True,
        help="2..8 reviewed archives; LAST archive is the fixed anchor",
    )
    p.add_argument("--model", default="gpt-6-luna")
    p.add_argument("--output-dir", type=Path)
    p = subs.add_parser("select-pair", help="at most one AFS call; prepare 3 scenes, never a robot")
    p.add_argument("--session", type=Path, required=True)
    group = p.add_mutually_exclusive_group()
    group.add_argument("--live", action="store_true")
    group.add_argument("--response", type=Path, help="validate saved response without API resend")
    for name in ("plan", "init"):
        p = subs.add_parser(name, help="offline: fixed single-axis contrasts")
        p.add_argument("--run", type=Path, action="append", required=True)
        p.add_argument("--axis", required=True)
        p.add_argument("--values", type=float, nargs="+", required=True)
        p.add_argument("--repeats", type=int, default=1)
        if name == "init":
            p.add_argument("--output-dir", type=Path)
    for name in ("run", "status", "report", "next", "resolve"):
        p = subs.add_parser(name)
        p.add_argument("--suite", type=Path, required=True)
        if name == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--max-new-attempts", type=int, default=1)
            p.add_argument("--continue-after-exclusion", action="store_true")
        if name == "resolve":
            p.add_argument("--note", required=True)
        if name == "next":
            mode = p.add_mutually_exclusive_group()
            mode.add_argument(
                "--live", action="store_true", help="at most ONE AFS call, never a robot"
            )
            mode.add_argument(
                "--response", type=Path, help="reuse saved completed API response without resending"
            )
            p.add_argument("--model", default="gpt-6-luna")
            p.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.op in {"prepare-pair", "select-pair"}:
            from failure_client.experiments.afs_paired_contrast import PairedSelection

            if args.op == "prepare-pair":
                root = PairedSelection.prepare(
                    args.output_dir or RUNTIME / (stamp() + "_paired"), args.run, model=args.model
                )
                state, _ = PairedSelection(root).store.load()
                print(
                    "PAIRED_PLAN="
                    + json.dumps(state["lock"]["context"]["search_selection"], ensure_ascii=False)
                )
                print(f"AFS_SELECTION={root}; no API or robot launched")
                print(f"AFS_REQUEST={root / 'request.json'}")
            else:
                print(
                    f"AFS_SELECTION={args.session.resolve()}; at most one AFS call; robot disabled",
                    flush=True,
                )
                target = PairedSelection(args.session).select(
                    live=args.live, response_path=args.response
                )
                print(f"CONTRAST_SUITE={target}; no robot launched")
                print(f"PREVIEW={target / 'preview/index.html'}")
                print(f"REPORT={BehaviorRegression(target).report()}")
            return 0
        if args.op in {"plan", "init"}:
            plan = contrast_plan(args.run, axis=args.axis, values=args.values, repeats=args.repeats)
            display = {
                k: plan[k]
                for k in (
                    "mode",
                    "axis",
                    "max_attempts",
                    "robot_api_call_upper_bound",
                    "afs_requests",
                    "limits",
                )
            }
            display["scenes"] = [
                {"role": c["contrast_role"], "value": c["scene"][args.axis]} for c in plan["cases"]
            ]
            display["robot"] = plan["cases"][0]["target_config"]["robot"]
            print("CONTRAST_PLAN=" + json.dumps(display, ensure_ascii=False))
            if args.op == "init":
                root = args.output_dir or RUNTIME / stamp()
                BehaviorRegression.create(root, plan)
                print(f"CONTRAST_SUITE={root.resolve()}; no API or robot launched")
                print(f"PREVIEW={write_preview(root, plan)}")
            return 0
        suite = BehaviorRegression(args.suite)
        if suite.state["lock"]["plan"].get("mode") != MODE:
            raise ValueError("not an anchored contrast suite; do not alter frozen benchmarks")
        if args.op == "run":
            suite.run(
                live=args.live,
                max_new_attempts=args.max_new_attempts,
                continue_after_exclusion=args.continue_after_exclusion,
            )
        elif args.op == "resolve":
            suite.exclude_pending(note=args.note)
        elif args.op == "next":
            with suite.store.exclusive():
                suite.state, suite.revision = suite.store.load()
                suite._fresh()
                if suite.state["status"] != "COMPLETE" or suite.state["pending"] is not None:
                    raise ValueError(
                        "finish and inspect all contrast attempts before choosing the next step"
                    )
                paths = [r["source"]["path"] for r in suite.state["lock"]["plan"]["history"]]
                paths += [a["episode"]["source"]["path"] for a in suite.state["attempts"]]
                memory, candidate, ctx, body = next_request(paths, model=args.model)
                root = (args.output_dir or RUNTIME / (stamp() + "_next")).resolve()
                if any(
                    root.is_relative_to(Path(p).resolve()) or Path(p).resolve().is_relative_to(root)
                    for p in paths
                ):
                    raise ValueError("next output must be separate from source archives")
                root.mkdir(parents=True, exist_ok=False)
                selection_costs = list(suite.state["lock"]["plan"].get("selection_costs", []))
                if body:
                    atomic_json(root / "context.json", ctx)
                    atomic_json(root / "request.json", body)
                    if args.live or args.response:
                        from llm_afs import provider

                        started = time.monotonic()
                        if args.live:
                            atomic_json(
                                root / "intent.json",
                                {"afs_calls_attempted": 1, "automatic_retries": 0},
                            )
                        try:
                            response = (
                                provider.call(body, timeout=300)
                                if args.live
                                else json.loads(args.response.read_text())
                            )
                            atomic_json(root / "response.json", response)
                            cost = {
                                "origin": "openai_api" if args.live else "saved_response",
                                "request_dir": str(root),
                                "source_response": str(args.response.resolve())
                                if args.response
                                else None,
                                "new_calls_attempted": int(args.live),
                                "requested_model": args.model,
                                "returned_model": response.get("model"),
                                "usage": response.get("usage"),
                                "wall_s": time.monotonic() - started if args.live else None,
                            }
                            atomic_json(root / "usage.json", cost)
                            selection_costs.append(cost)
                            suite._fresh()
                            # Verify evidence again after inference; never trust a stale proposal.
                            fresh_memory, _, fresh_ctx, _ = next_request(paths, model=args.model)
                            if fresh_ctx != ctx:
                                raise ValueError("evidence context changed during inference")
                            candidate, _ = next_selection(
                                fresh_memory, raw=provider.extract_proposal(response)
                            )
                        except Exception as exc:
                            atomic_json(
                                root / "error.json",
                                {"type": type(exc).__name__, "message": clean(exc)},
                            )
                            raise
                if candidate:
                    atomic_json(root / "candidate.json", candidate)
                    plan = selected_plan(paths, candidate)
                    # Keep selection costs separate from the original suite accounting.
                    plan["selection_request_dir"] = str(root)
                    plan["selection_costs"] = selection_costs
                    target = root / "suite"
                    BehaviorRegression.create(
                        target, plan, execution_origin=suite.state["lock"]["execution_origin"]
                    )
                    print(
                        f"CONTRAST_SUITE={target}; "
                        f"max robot calls={plan['robot_api_call_upper_bound']}; no robot launched"
                    )
                    print(f"PREVIEW={write_preview(target, plan)}")
                else:
                    print(
                        f"AFS_REQUEST={root / 'request.json'}; prepared only; "
                        "use next --live for one AFS proposal"
                    )
                return 0
        if args.op in {"run", "report"}:
            print(f"REPORT={suite.report()}")
        print(json.dumps(suite.summary(), indent=2, ensure_ascii=False))
        return 2 if suite.state["status"] in {"NEEDS_ATTENTION", "COMPLETE_WITH_EXCLUSIONS"} else 0
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        parser.exit(
            2, f"Contrast stopped: {type(exc).__name__}: {clean(exc)}\nNo automatic retry.\n"
        )


if __name__ == "__main__":
    raise SystemExit(main())
