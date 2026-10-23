"""Separate static-box AFS/Random pilot; plan/init/status never execute robot or API."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
import run_robot_arm_search as legacy  # noqa: E402
from watch_robot_arm_search import Observer, display, stop_group  # noqa: E402

from robot_arm import capability, obstacles, placement, search  # noqa: E402
from robot_arm import obstacle_search as experiment  # noqa: E402

DEFAULT = PROJECT / "config/robot_arm_obstacle_comparison.json"
ROOT = PROJECT / "experiments/robot_arm_libero/obstacle_comparison_v1"


def sources(c):
    return legacy.sources(c) + [
        Path(__file__).resolve(),
        PROJECT / "tools/watch_robot_arm_search.py",
        PROJECT / "src/robot_arm/obstacle_search.py",
        PROJECT / "src/robot_arm/obstacles.py",
        PROJECT / "src/robot_arm/capability.py",
    ]


def worker(d):
    design = experiment.verify(d.parents[2])
    c = design["experiment"]
    value = search.read(d / "candidate.json")
    seed = int(d.parents[1].name.split("_")[1])
    index = int(d.name.split("_")[1])
    expected = experiment.candidate(design, value["parameters"], seed, index, value["hypothesis"])
    if expected != value or search.read(d / "robot_intent.json") != value:
        raise ValueError("candidate/intent/domain mismatch")
    placement.save(d / "worker_started.json", {"pid": os.getpid()})
    try:
        result = obstacles.run(c, value, d)
    except Exception:
        import traceback

        traceback.print_exc()
        result = {
            "status": "INCONCLUSIVE",
            "task_outcome": None,
            "reason": "worker_execution_or_initial_geometry_error",
        }
    placement.save(d / "receipt.json", result)
    placement.save(d / "measurement.json", capability.case_measure(d, result))
    experiment.seal(d)
    return 0 if result["status"] == "VALID" else 1


def runner(c, value, d):
    placement.save(d / "manifest.json", {"mode": "manual", "config": c})
    print("ROBOT_START", d, flush=True)
    observer = Observer(d)
    display(observer, phase="장애물 AFS/Random 실행 준비")
    with (d / "run.log").open("x") as stream:
        child = subprocess.Popen(
            [
                c["robot"]["python"],
                "-u",
                str(Path(__file__).resolve()),
                "_worker",
                "--output",
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
        except KeyboardInterrupt:
            stop_group(child)
            raise
    if child.returncode or not (d / "evidence_manifest.json").exists():
        raise RuntimeError("worker stopped; preserve evidence; no retry")
    print("ROBOT_RESULT", search.read(d / "receipt.json")["task_outcome"], flush=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("op", choices=["plan", "init", "run", "status", "_worker"])
    p.add_argument("--config", type=Path, default=DEFAULT)
    p.add_argument("--output", type=Path, default=ROOT)
    p.add_argument("--live", action="store_true")
    p.add_argument("--max-new-attempts", type=int, default=1)
    a = p.parse_args()
    root = a.output.resolve()
    if a.op == "_worker":
        return worker(root)
    if a.op in {"plan", "init"}:
        design = experiment.validate(search.read(a.config))
        c = design["experiment"]
        plan = {
            "design": design,
            "robot_attempt_cap": len(c["seeds"]) * c["per_arm"] * 2,
            "afs_request_cap": len(c["seeds"]) * (c["per_arm"] - c["bootstrap"]),
            "planned_random": [
                {
                    "seed": s,
                    "index": i,
                    "candidate": experiment.candidate(
                        design, experiment.uniform(design, s, i), s, i, "uniform"
                    ),
                }
                for s in c["seeds"]
                for i in range(c["per_arm"])
            ],
            "executed": False,
        }
        if a.op == "plan":
            print(json.dumps(plan, indent=2))
        else:
            if root.exists():
                raise FileExistsError("preserve existing output")
            manifest = search.freeze(c, sources(c))
            manifest.update(mode=experiment.VERSION, design=design)
            root.mkdir(parents=True, exist_ok=False)
            placement.save(root / "manifest.json", manifest)
            (root / "manifest.sha256").write_text(search.sha(root / "manifest.json") + "\n")
            placement.save(root / "plan.json", plan)
            print("PREPARED", root, "; no API/GPU/policy execution")
    elif a.op == "status":
        # Read saved evidence without rehashing GBs of model weights.
        if (root / "manifest.sha256").read_text().strip() != search.sha(root / "manifest.json"):
            raise ValueError("manifest changed")
        print(json.dumps(experiment.summary(root), indent=2))
    else:
        if not a.live:
            raise ValueError("explicit --live required")
        from robot_arm.openrouter import call, require_key

        require_key()

        def propose(body):
            print("AFS_REQUEST", body["model"], flush=True)
            return call(body, timeout=300)

        print(json.dumps(experiment.run(root, runner, propose, a.max_new_attempts), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
