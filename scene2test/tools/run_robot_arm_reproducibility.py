"""Replay every valid frozen environment twice; total three observations, no AFS calls."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from watch_robot_arm_search import Observer, display, stop_group  # noqa: E402

from robot_arm import free_pair_obstacles, phase_measure, placement, search  # noqa: E402
from robot_arm import free_pair_search as original  # noqa: E402

SOURCE = PROJECT / "experiments/robot_arm_libero/free_pair_continuation_v5"
ROOT = PROJECT / "experiments/robot_arm_libero/free_pair_reproducibility_3x_v1"
VERSION = "frozen-environment-three-observations-v1"


def verify(root):
    search.verify(root)
    m = search.read(root / "manifest.json")
    if m.get("mode") != VERSION or m.get("total_observations") != 3:
        raise ValueError("wrong reproducibility contract")
    return m


def prepare(source, root):
    if root.exists():
        raise FileExistsError("preserve existing output; use run/status")
    design = original.verify(source)
    summary = original.summary(source)
    if not summary["attempt_budget_complete"]:
        raise ValueError("source campaign must be complete with no pending intents")
    inherited = {
        str(source / name): search.sha(source / name)
        for name in ("manifest.json", "manifest.sha256")
    }
    cases, excluded = [], []
    for d in sorted(source.glob("seed_*/*/attempt_*")):
        candidate = search.read(d / "candidate.json")
        receipt = original.receipt(d, candidate)
        for name, digest in search.read(d / "evidence_manifest.json").items():
            inherited[str(d / name)] = digest
        inherited[str(d / "evidence_manifest.json")] = search.sha(d / "evidence_manifest.json")
        relative = str(d.relative_to(source))
        if receipt["status"] != "VALID":
            excluded.append({"case": relative, "receipt": receipt})
            continue
        cases.append({"case": relative, "candidate": candidate, "original_receipt": receipt})
    if not cases:
        raise ValueError("no valid source environments")
    old = search.read(source / "manifest.json")
    m = {
        "mode": VERSION,
        "config": design["experiment"],
        "design": design,
        "source": str(source),
        "source_hashes": {
            **old["source_hashes"],
            str(Path(__file__).resolve()): search.sha(Path(__file__)),
            str(PROJECT / "tools/repeat_robot_arm_three_times.sh"): search.sha(
                PROJECT / "tools/repeat_robot_arm_three_times.sh"
            ),
        },
        "model_hashes": old["model_hashes"],
        "inherited_artifacts": {**old.get("inherited_artifacts", {}), **inherited},
        "total_observations": 3,
        "additional_rounds": [2, 3],
        "cases": cases,
        "excluded_source_slots": excluded,
        "new_robot_attempt_cap": 2 * len(cases),
        "new_control_step_cap": 2 * len(cases) * design["experiment"]["robot"]["max_episode_steps"],
        "afs_request_cap": 0,
        "seed_policy": (
            "Exact original scene_seed and background_seed; independent worker process each time"
        ),
        "scope": (
            "Within-setting same-seed repeatability, "
            "not independent search replication or causal proof"
        ),
    }
    root.mkdir(parents=True, exist_ok=False)
    placement.save(root / "manifest.json", m)
    (root / "manifest.sha256").write_text(search.sha(root / "manifest.json") + "\n")
    return m


def checked_receipt(d, expected):
    if search.read(d / "candidate.json") != expected:
        raise ValueError("repeat candidate differs from original")
    r = original.receipt(d, expected)
    if r["status"] == "VALID" and r.get("scene_seed") != expected["scene_seed"]:
        raise ValueError("repeat scene seed mismatch")
    return r


def report(root):
    if (root / "manifest.sha256").read_text().strip() != search.sha(root / "manifest.json"):
        raise ValueError("manifest changed")
    m = search.read(root / "manifest.json")
    rows = []
    totals = {
        method: {
            "environments": 0,
            "new_attempts": 0,
            "new_valid": 0,
            "new_excluded": 0,
            "pending": 0,
            "complete_three": 0,
            "three_fail": 0,
            "three_pass": 0,
            "mixed": 0,
            "original_fail": 0,
            "original_fail_three_fail": 0,
        }
        for method in ("afs", "random")
    }
    for case in m["cases"]:
        method = case["case"].split("/")[1]
        t = totals[method]
        t["environments"] += 1
        outcomes = [case["original_receipt"]["task_outcome"]]
        t["original_fail"] += int(outcomes[0] == "FAIL")
        for repeat in m["additional_rounds"]:
            d = root / f"round_{repeat}" / case["case"]
            if (d / "receipt.json").exists():
                r = checked_receipt(d, case["candidate"])
                t["new_attempts"] += 1
                valid = r["status"] == "VALID"
                t["new_valid"] += int(valid)
                t["new_excluded"] += int(not valid)
                outcomes.append(r["task_outcome"] if valid else "INCONCLUSIVE")
            elif (d / "robot_intent.json").exists():
                t["new_attempts"] += 1
                t["pending"] += 1
                outcomes.append("PENDING")
            else:
                outcomes.append("NOT_RUN")
        complete = all(o in {"PASS", "FAIL"} for o in outcomes)
        failures = outcomes.count("FAIL")
        if complete:
            t["complete_three"] += 1
            t["three_fail"] += int(failures == 3)
            t["three_pass"] += int(failures == 0)
            t["mixed"] += int(0 < failures < 3)
            t["original_fail_three_fail"] += int(outcomes[0] == "FAIL" and failures == 3)
        rows.append(
            {
                "case": case["case"],
                "outcomes": outcomes,
                "fail_count": failures,
                "complete_three": complete,
            }
        )
    return {
        "source": m["source"],
        "totals": totals,
        "environments": rows,
        "excluded_source_slots": m["excluded_source_slots"],
        "complete": all(t["complete_three"] == t["environments"] for t in totals.values()),
        "afs_requests": 0,
        "scope": m["scope"],
        "warning": (
            "Three repeats share environment and seed; do not pool as "
            "independent samples or new unique failures."
        ),
    }


def run(root, runner, max_new):
    print("REPEAT_VERIFY source/model/evidence hashes; no robot dispatch yet", flush=True)
    m = verify(root)
    spent = 0
    # Round order exposes both methods before moving to the next full round.
    for repeat in m["additional_rounds"]:
        for case in m["cases"]:
            value = case["candidate"]
            d = root / f"round_{repeat}" / case["case"]
            if (d / "receipt.json").exists():
                if checked_receipt(d, value)["status"] != "VALID":
                    raise RuntimeError("excluded repeat preserved; no replacement")
                continue
            if (d / "robot_intent.json").exists():
                raise RuntimeError("pending repeat intent; preserve evidence; never resend")
            if spent >= max_new:
                return report(root)
            d.mkdir(parents=True, exist_ok=True)
            if (d / "candidate.json").exists():
                if search.read(d / "candidate.json") != value:
                    raise ValueError("candidate changed")
            else:
                placement.save(d / "candidate.json", value)
            placement.save(d / "robot_intent.json", value)
            spent += 1
            runner(m["config"], value, d)
            if checked_receipt(d, value)["status"] != "VALID":
                raise RuntimeError("excluded repeat preserved; no replacement")
    return report(root)


def worker(root, directory):
    m = verify(root)
    matches = [
        c
        for c in m["cases"]
        for repeat in m["additional_rounds"]
        if root / f"round_{repeat}" / c["case"] == directory
    ]
    if len(matches) != 1:
        raise ValueError("unplanned worker directory")
    value = matches[0]["candidate"]
    if (
        search.read(directory / "candidate.json") != value
        or search.read(directory / "robot_intent.json") != value
    ):
        raise ValueError("worker candidate/intent mismatch")
    if (directory / "worker_started.json").exists():
        raise RuntimeError("worker already started; no retry")
    placement.save(directory / "worker_started.json", {"pid": os.getpid()})
    try:
        result = free_pair_obstacles.run(m["config"], value, directory)
    except Exception:
        import traceback

        traceback.print_exc()
        result = {
            "status": "INCONCLUSIVE",
            "task_outcome": None,
            "reason": "repeat_worker_execution_or_initial_geometry_error",
        }
    placement.save(directory / "receipt.json", result)
    placement.save(directory / "measurement.json", phase_measure.case_measure(directory, result))
    original.seal(directory)
    return 0 if result["status"] == "VALID" else 1


def runner(root, c, value, d):
    placement.save(d / "manifest.json", {"mode": "manual", "config": c})
    print("REPEAT_START", d.relative_to(root), flush=True)
    observer = Observer(d)
    display(observer, phase="동일 환경 총 3회 측정 / 로봇 준비")
    with (d / "run.log").open("x") as stream:
        child = subprocess.Popen(
            [
                c["robot"]["python"],
                "-u",
                str(Path(__file__).resolve()),
                "_worker",
                "--output",
                str(root),
                "--directory",
                str(d),
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            while child.poll() is None:
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    display(observer)
        except BaseException:
            stop_group(child)
            raise
    if child.returncode or not (d / "evidence_manifest.json").exists():
        raise RuntimeError("worker stopped; preserve evidence; no retry")
    print("REPEAT_RESULT", search.read(d / "receipt.json")["task_outcome"], flush=True)


def save_summary(root, result):
    # Summary is derived and replaceable; execution evidence remains exclusive.
    with tempfile.NamedTemporaryFile(
        mode="w", dir=root, prefix="summary_", suffix=".tmp", delete=False
    ) as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
        temporary = stream.name
    os.replace(temporary, root / "summary.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["plan", "run", "status", "_worker"])
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=ROOT)
    parser.add_argument("--directory", type=Path)
    parser.add_argument("--max-new-attempts", type=int, default=46)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if args.op == "_worker":
        return worker(root, args.directory.resolve())
    if args.op == "status":
        print(json.dumps(report(root), indent=2))
        return 0
    if args.op == "plan":
        s = original.summary(args.source.resolve())
        valid = sum(t["valid"] for t in s["totals"].values())
        print(
            json.dumps(
                {
                    "source": str(args.source.resolve()),
                    "valid_environments": valid,
                    "total_observations": 3,
                    "new_robot_attempts": 2 * valid,
                    "afs_requests": 0,
                    "executed": False,
                },
                indent=2,
            )
        )
        return 0
    if not args.live or not 1 <= args.max_new_attempts <= 46:
        raise ValueError("explicit --live and max-new-attempts 1..46 required")
    root.parent.mkdir(parents=True, exist_ok=True)
    # Lock is outside root so initialization remains exclusive and repeat invocation is safe.
    with (root.parent / (root.name + ".lock")).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not root.exists():
            print("REPEAT_PREPARE preserving original evidence; 0 AFS requests", flush=True)
            prepare(args.source.resolve(), root)
        try:
            result = run(root, lambda c, v, d: runner(root, c, v, d), args.max_new_attempts)
        except BaseException:
            save_summary(root, report(root))
            raise
        save_summary(root, result)
        print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
