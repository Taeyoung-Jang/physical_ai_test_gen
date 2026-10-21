"""Standard-tier continuation: preserve one Flex exclusion, at most five NEW attempts."""

import argparse
import json
import os
from pathlib import Path

from failure_client.evaluation.behavior_measures import verify_episode_files
from failure_client.evaluation.goal_run_reader import read_goal_run, read_json
from failure_client.evaluation.research_records import RunInput
from failure_client.experiments.behavior_regression import BehaviorRegression, replay_plan
from failure_client.experiments.local_goal_adapter import atomic_json
from llm_afs.behavior import digest
from robot_vlm.debug_log import clean

RUNTIME = Path("/workspace/g1_failure/runtime")
SOURCE = RUNTIME / "behavior_regression/sol_flex_20261020_v1"
ROOT = RUNTIME / "behavior_regression/sol_standard_20261020_v1"
GROUPS = [
    (
        "pass",
        1,
        RUNTIME
        / "afs_autonomous/20261018T160156_325966Z_numeric_recovery/attempts/attempt_00002/rollout",
    ),
    (
        "safety",
        2,
        RUNTIME / "trajectory_feedback/20261019T134446_66195/afs/attempts/attempt_00000/rollout",
    ),
    (
        "occupied",
        2,
        RUNTIME / "trajectory_feedback/20261019T134446_66195/afs/attempts/attempt_00005/rollout",
    ),
]


def prior_snapshot():
    # Read the old suite only. Never call its run/_fresh or replace its frozen lock.
    source = BehaviorRegression(SOURCE)
    state = source.state
    if len(state["attempts"]) != 1 or state["pending"] is not None:
        raise ValueError("expected exactly one finalized prior Flex attempt")
    saved = state["attempts"][0]["episode"]
    path = SOURCE / "attempts/attempt_00000/rollout"
    record = read_goal_run(RunInput(path=str(path)))
    verify_episode_files(record)
    result = read_json(path / "result.json")
    protocol = read_json(path / "protocol.json")
    if (
        record.status != "INCONCLUSIVE"
        or record.evidence_id != saved["evidence_id"]
        or record.artifact_hashes != saved["artifact_hashes"]
        or result.get("reason") != "api_http_429"
        or result.get("api_calls_attempted") != 1
        or result.get("live_actions_accepted") != 0
        or protocol.get("service_tier") != "flex"
        or "Flex processing is temporarily unavailable"
        not in result.get("error_diagnostic", {}).get("api_error_message", "")
    ):
        raise ValueError("prior exclusion is not the verified first-call Flex capacity rejection")
    return {
        "source": str(SOURCE),
        "state_sha256": digest(state),
        "excluded_episode": record.model_dump(),
        "spent_attempts": 1,
        "spent_api_requests": 1,
        "usage_status": "unknown_not_zero",
    }


def plans():
    result = []
    for name, repeats, baseline in GROUPS:
        plan = replay_plan([baseline], repeats=repeats, model="gpt-6.1-sol", service_tier="default")
        if len(plan["cases"]) != 1 or plan["max_attempts"] != repeats or plan["afs_requests"] != 0:
            raise ValueError("unexpected regression plan")
        robot = plan["cases"][0]["target_config"]["robot"]
        if robot["max_calls"] != 10:
            raise ValueError("approved per-episode budget changed")
        result.append((name, plan))
    return result


def load_manifest(root):
    wrapped = read_json(root / "manifest.json")
    manifest = wrapped["manifest"]
    if wrapped["sha256"] != digest(manifest) or manifest["prior"] != prior_snapshot():
        raise ValueError("continuation manifest or prior Flex evidence changed")
    for name, _, _ in GROUPS:
        suite = BehaviorRegression(root / name)
        if digest(suite.state["lock"]["plan"]) != manifest["plans"][name]:
            raise ValueError("standard regression plan changed")
    return manifest


def summary(root):
    manifest = load_manifest(root)
    rows = [BehaviorRegression(root / name).summary() for name, _, _ in GROUPS]
    complete = all(row["status"] == "COMPLETE" for row in rows)
    attempts = sum(c["attempted"] for row in rows for c in row["cases"])
    return {
        "root": str(root),
        "status": "COMPLETE" if complete else "INCOMPLETE",
        "prior_flex_excluded_attempts": 1,
        "new_standard_attempts": attempts,
        "combined_attempts": 1 + attempts,
        "combined_attempt_cap": 6,
        "new_robot_call_upper_bound": 50,
        "afs_requests": 0,
        "prior_usage_status": manifest["prior"]["usage_status"],
        "new_standard_suites": rows,
        "limits": [
            "Separate model/tier comparison, not AFS discovery/Gain",
            "Normal case has one Standard repeat, failure cases two each",
            "Prior Flex exclusion is NOT a Standard outcome or FDR sample",
            "No automatic retry, budget reset or continuation after exclusion",
        ],
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "operation", nargs="?", default="plan", choices=["plan", "init", "run", "status", "report"]
    )
    p.add_argument("--root", type=Path, default=ROOT)
    p.add_argument("--live", action="store_true")
    args = p.parse_args(argv)
    if args.live and args.operation != "run":
        p.error("--live belongs to run only")
    try:
        if args.operation in {"plan", "init"}:
            prior = prior_snapshot()
            planned = plans()
            print(
                "PLAN="
                + json.dumps(
                    {
                        "prior_flex_exclusions": 1,
                        "new_standard_attempts": 5,
                        "new_robot_call_upper_bound": 50,
                        "afs_requests": 0,
                        "model": "gpt-6.1-sol",
                        "service_tier": "default",
                        "groups": [
                            {"name": name, "attempts": plan["max_attempts"]}
                            for name, plan in planned
                        ],
                    }
                ),
                flush=True,
            )
            if args.operation == "init":
                if args.root.resolve().is_relative_to(
                    SOURCE.resolve()
                ) or SOURCE.resolve().is_relative_to(args.root.resolve()):
                    raise ValueError("new output must be separate from prior Flex suite")
                args.root.mkdir(parents=True, exist_ok=False)
                for name, plan in planned:
                    BehaviorRegression.create(args.root / name, plan)
                manifest = {
                    "schema": "sol-standard-five-attempt-continuation-v1",
                    "prior": prior,
                    "plans": {name: digest(plan) for name, plan in planned},
                }
                atomic_json(
                    args.root / "manifest.json", {"manifest": manifest, "sha256": digest(manifest)}
                )
                print(f"ROOT={args.root}; no API or robot launched")
            return 0
        load_manifest(args.root)
        if args.operation == "run":
            if not args.live or not os.getenv("OPENAI_API_KEY", "").strip():
                raise ValueError("run requires --live and OPENAI_API_KEY in this process")
            for name, _, _ in GROUPS:
                suite = BehaviorRegression(args.root / name)
                result = suite.run(live=True, max_new_attempts=2)
                print(f"REPORT={suite.report()}", flush=True)
                if result["status"] != "COMPLETE":
                    break
        elif args.operation == "report":
            for name, _, _ in GROUPS:
                print(f"REPORT={BehaviorRegression(args.root / name).report()}", flush=True)
        value = summary(args.root)
        atomic_json(args.root / "summary.json", value)
        print("SUMMARY=" + json.dumps(value, ensure_ascii=False), flush=True)
        return 0 if value["status"] == "COMPLETE" or args.operation != "run" else 2
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        print(f"STOPPED={type(exc).__name__}: {clean(str(exc))}; no automatic retry", flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
