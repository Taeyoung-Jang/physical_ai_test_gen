"""Four additional Random draws; original archives stay in place and are never rebound."""

import argparse
import hashlib
import json
import os
import runpy
import threading
from pathlib import Path

from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import RunInput
from failure_client.experiments.local_goal_adapter import LocalGoalRunner, atomic_json
from failure_client.experiments.research_protocol import CampaignConfig
from failure_client.methods.matched_local import random_candidate
from llm_afs.behavior import digest

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "development/humanoid_luna_128k_20261023_v5/random"
ROOT = PROJECT / "development/humanoid_luna_128k_random7_20261024_v6"


def support():
    return runpy.run_path(str(PROJECT / "tools/run_humanoid_random_assessment.py"))


def sealed(path):
    value = json.loads(Path(path).read_text())
    if value["sha256"] != digest(value["value"]):
        raise ValueError("sealed artifact changed")
    return value["value"]


def save(path, value):
    atomic_json(path, {"value": value, "sha256": digest(value)})


def prepare(source, root, *, fingerprint_fn=None):
    source, root = Path(source).resolve(), Path(root).resolve()
    if root.exists() or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("new disjoint output directory required")
    f = support()
    m, states = f["snapshot"](source)
    if len(states) != 1:
        raise ValueError("one Random seed required")
    state = states[0]
    if (
        state["status"] != "COMPLETE"
        or state["pending"] is not None
        or state["selected"] is not None
        or state["proposals"]
        or len(state["attempts"]) != 3
        or any(a["episode"]["status"] != "VALID" for a in state["attempts"])
    ):
        raise ValueError("exactly three complete valid Random results required")
    cfg = CampaignConfig.model_validate(m["robot_config"])
    if (fingerprint_fn or f["fingerprint"])(cfg) != m["environment"]:
        raise ValueError("source/resources/runtime drift")
    seed = m["design"]["seeds"][0]
    value = {
        "schema_version": "random-readonly-prefix-plus-four-v1",
        "source": str(source),
        "source_manifest_sha256": digest(m),
        "source_state_sha256": digest(state),
        "seed": seed,
        "robot_config": m["robot_config"],
        "environment": m["environment"],
        "condition_id": m["reference_condition_id"],
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_results": [a["episode"] for a in state["attempts"]],
        "target_valid": 7,
        "new_attempt_cap": 4,
        "afs_request_cap": 0,
        "new_robot_api_call_cap": 4 * cfg.robot.max_calls,
        "posthoc_extension": (
            "Sample count expanded after observing AFS; not held-out superiority evidence"
        ),
        "draws": [
            random_candidate(
                m["matched_local"],
                m["scene_domain"],
                m["design"]["search"]["min_axis_change_fraction"],
                seed,
                i - 1,
            )
            for i in range(3, 7)
        ],
    }
    root.mkdir(parents=True)
    save(root / "plan.json", value)
    save(root / "state.json", {"plan_sha256": digest(value), "results": [], "pending": None})
    return value


def verify(root, *, fingerprint_fn=None):
    plan, state = sealed(root / "plan.json"), sealed(root / "state.json")
    if state["plan_sha256"] != digest(plan):
        raise ValueError("plan binding changed")
    f = support()
    m, states = f["snapshot"](Path(plan["source"]))
    if (
        digest(m) != plan["source_manifest_sha256"]
        or digest(states[0]) != plan["source_state_sha256"]
    ):
        raise ValueError("original Random source changed")
    cfg = CampaignConfig.model_validate(plan["robot_config"])
    if (fingerprint_fn or f["fingerprint"])(cfg) != plan["environment"] or hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest() != plan["script_sha256"]:
        raise ValueError("frozen code/resources/runtime changed")
    return plan, state, cfg


def report(root, plan, state):
    records = plan["original_results"] + state["results"]
    ids = [r["evidence_id"] for r in records if r.get("evidence_id")]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate evidence cannot count as new episodes")
    valid = [r for r in records if r["status"] == "VALID"]
    value = {
        "target_valid": 7,
        "valid": len(valid),
        "pass": sum(r["task_outcome"] == "PASS" for r in valid),
        "fail": sum(r["task_outcome"] == "FAIL" for r in valid),
        "excluded": len(records) - len(valid),
        "pending": state["pending"],
        "complete": len(valid) == 7,
        "afs_requests": 0,
        "original_results_counted_once": 3,
        "new_attempted": len(state["results"]),
        "records": records,
        "scope": plan["posthoc_extension"],
        "safety": "Additional cases not aggregated here; goal PASS is not a safety verdict",
    }
    save(root / "summary.json", value)
    print(
        f"Random 유효 {len(valid)}/7 | PASS {value['pass']} FAIL {value['fail']} "
        f"제외 {value['excluded']}",
        flush=True,
    )
    print(f"SUMMARY={root / 'summary.json'}", flush=True)
    return value


def run(root, *, live=False, runner=None, fingerprint_fn=None):
    root = Path(root).resolve()
    import fcntl

    with (root / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan, state, cfg = verify(root, fingerprint_fn=fingerprint_fn)
        if not live:
            return report(root, plan, state)
        if runner is None and len(state["results"]) < 4 and not os.getenv("OPENROUTER_API_KEY"):
            raise ValueError("set OPENROUTER_API_KEY in your terminal")
        while len(state["results"]) < 4:
            if any(r["status"] != "VALID" for r in state["results"]):
                break
            index = len(state["results"])
            directory = root / f"attempt_{index + 3:05d}"
            if state["pending"] is not None:
                if not (directory / "receipt.json").exists():
                    raise ValueError("existing execution intent has no receipt; never resend")
            else:
                if directory.exists():
                    raise ValueError("unexpected existing attempt directory; never overwrite")
                state["pending"] = index
                save(root / "state.json", state)
                print(f"Random 추가 시험 {index + 1}/4 (기존 draw index {index + 3})", flush=True)
                stop = threading.Event()

                def heartbeat():
                    while not stop.wait(30):
                        print("진행 중: 추가 Random 로봇 실행", flush=True)

                threading.Thread(target=heartbeat, daemon=True).start()
                try:
                    (runner or LocalGoalRunner())(
                        cfg, directory, plan["draws"][index]["parameters"]
                    )
                finally:
                    stop.set()
            record = read_goal_run(
                RunInput(
                    path=str(directory / "rollout"),
                    method="random",
                    seed=plan["seed"],
                    stage="discovery",
                )
            )
            receipt = json.loads((directory / "receipt.json").read_text())
            if receipt.get("interrupted"):
                record = record.model_copy(
                    update={
                        "status": "INCONCLUSIVE",
                        "task_outcome": None,
                        "exclusion_reason": "interrupted_execution",
                    }
                )
            if record.status == "VALID" and record.condition_id != plan["condition_id"]:
                raise ValueError("robot condition changed")
            state["results"].append(record.model_dump())
            state["pending"] = None
            save(root / "state.json", state)
            print(f"결과: {record.status} {record.task_outcome}", flush=True)
            report(root, plan, state)
            verify(root, fingerprint_fn=fingerprint_fn)
        return report(root, plan, state)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["prepare", "run", "status"])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.op == "prepare":
        prepare(args.source, args.output)
        print("PREPARED: existing three results stay in place; zero API calls", flush=True)
    else:
        value = run(args.output, live=args.live and args.op == "run")
        if args.op == "run" and not value["complete"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
