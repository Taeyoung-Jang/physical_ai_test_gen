"""Two independent, single-episode LIBERO Object/Goal development probes."""

import argparse
import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

from run_robot_arm_baseline import SOURCES, check, digest, write

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT = PROJECT / "config/robot_arm_object_goal.json"
OUTPUT = PROJECT / "experiments/robot_arm_libero/object_goal_smoke_20261024_v1"
TASKS = {
    "libero_object": "pick_up_the_butter_and_place_it_in_the_basket",
    "libero_goal": "open_the_middle_drawer_of_the_cabinet",
}


def load(path):
    c = json.loads(Path(path).read_text())
    if (
        c["schema_version"] != "robot-arm-object-goal-smoke-v1"
        or c["max_episode_steps"] != 300
        or c["n_action_steps"] != 8
        or c["afs_requests"] != 0
        or c["environment_changes"] != []
        or len(c["cases"]) != 2
        or {r["suite"]: r["task"] for r in c["cases"]} != TASKS
        or any(type(r["seed"]) is not int or r["seed"] < 0 for r in c["cases"])
    ):
        raise ValueError("unsupported two-episode contract")
    for case in c["cases"]:
        if Path(case["model_path"]).name != case["suite"]:
            raise ValueError("suite/checkpoint mismatch")
    return c


def resources(c):
    return {r["suite"]: check(dict(c, model_path=r["model_path"])) for r in c["cases"]}


def hashes(c):
    upstream = Path(c["upstream_root"])
    files = [upstream / p for p in SOURCES]
    files += [Path(__file__).resolve(), Path(__file__).with_name("run_robot_arm_baseline.py")]
    files += [Path(c["libero_config_path"]) / "config.yaml"]
    for case in c["cases"]:
        files.append(
            upstream
            / "external_dependencies/LIBERO/libero/libero/bddl_files"
            / case["suite"]
            / (case["task"] + ".bddl")
        )
        root = Path(case["model_path"])
        files.extend(p for p in sorted(root.rglob("*")) if p.is_file())
    return {str(p): digest(p) for p in files}


def verify(frozen):
    for name, expected in frozen["hashes"].items():
        if digest(name) != expected:
            raise ValueError("frozen source/model changed: " + name)


def status(output):
    rows = []
    for suite in TASKS:
        folder = output / suite
        row = {"suite": suite, "intent_exists": (folder / "intent.json").exists()}
        for name in ("result.json", "exclusion.json"):
            if (folder / name).is_file():
                row[name] = json.loads((folder / name).read_text())
        rows.append(row)
    return {"output": str(output), "cases": rows}


def worker(output, suite):
    frozen = json.loads((output / "manifest.json").read_text())
    c = load(output / "config.json")
    if c != frozen["config"]:
        raise ValueError("frozen config changed")
    verify(frozen)
    case = next(r for r in c["cases"] if r["suite"] == suite)
    folder = output / suite
    if json.loads((folder / "intent.json").read_text())["case"] != case:
        raise ValueError("missing/mismatched durable execution intent")
    write(folder / "worker_started.json", {"pid": os.getpid()})
    os.environ["LIBERO_CONFIG_PATH"] = c["libero_config_path"]
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, c["upstream_root"])
    from gr00t.eval.rollout_policy import run_gr00t_sim_policy

    result = run_gr00t_sim_policy(
        env_name="libero_sim/" + case["task"],
        n_episodes=1,
        max_episode_steps=c["max_episode_steps"],
        model_path=case["model_path"],
        n_envs=1,
        n_action_steps=c["n_action_steps"],
        video_dir=str(folder / "videos"),
        seed=case["seed"],
    )
    successes = list(result[1])
    lengths = result[2].get("episode_lengths", [])
    if len(successes) != 1 or len(lengths) != 1 or not 1 <= int(lengths[0]) <= 300:
        raise RuntimeError("missing/filtered/out-of-budget episode; not robot FAIL")
    write(
        folder / "result.json",
        {
            "status": "VALID",
            "task_outcome": "PASS" if successes[0] else "FAIL",
            "task_success": bool(successes[0]),
            "case": case,
            "episode_lengths": [int(x) for x in lengths],
            "success_rule": "upstream LIBERO check_success via upstream rollout collector",
            "sampling": c["sampling"],
        },
    )
    evidence = {
        str(p.relative_to(folder)): digest(p)
        for p in sorted(folder.rglob("*"))
        if p.is_file() and p.name != "run.log"
    }
    write(folder / "evidence.json", evidence)


def run(c, output):
    # Every invocation owns the root; existing intents are never dispatched again.
    if output.exists():
        print(json.dumps(status(output), indent=2))
        raise ValueError("existing run preserved; use status, no automatic replay")
    preflight = resources(c)
    if not all(r["local_resources_present"] for r in preflight.values()):
        raise ValueError("missing resources: " + json.dumps(preflight))
    print("Binding source and checkpoint hashes before execution", flush=True)
    frozen = {"config": c, "hashes": hashes(c)}
    output.mkdir(parents=True, exist_ok=False)
    write(output / "config.json", c)
    write(output / "manifest.json", frozen)
    write(output / "preflight.json", preflight)
    for case in c["cases"]:
        suite = case["suite"]
        folder = output / suite
        folder.mkdir()
        command = [
            c["python"],
            "-u",
            str(Path(__file__).resolve()),
            "_worker",
            "--output",
            str(output),
            "--suite",
            suite,
        ]
        write(folder / "intent.json", {"case": case, "command": command})
        print("Starting " + suite + ": " + case["task"], flush=True)
        with (folder / "run.log").open("x") as log:
            process = subprocess.Popen(
                command, cwd=c["upstream_root"], stdout=log, stderr=subprocess.STDOUT
            )
            try:
                while process.poll() is None:
                    try:
                        process.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        print(suite + " running; log=" + str(folder / "run.log"), flush=True)
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
                raise
            returncode = process.returncode
        if returncode or not (folder / "result.json").is_file():
            write(
                folder / "exclusion.json",
                {
                    "status": "INCONCLUSIVE",
                    "task_outcome": None,
                    "reason": "worker_error_or_missing_outcome",
                    "returncode": returncode,
                },
            )
            raise RuntimeError("worker stopped; preserve evidence, no retry/replacement")
        print((folder / "result.json").read_text(), flush=True)
    summary = status(output)
    write(output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["plan", "check", "run", "status", "_worker"])
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--suite", choices=list(TASKS))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if args.op == "status":
        print(json.dumps(status(output), indent=2))
    elif args.op == "_worker":
        worker(output, args.suite)
    else:
        c = load(args.config)
        if args.op == "plan":
            print(
                json.dumps(
                    {"config": c, "episodes": 2, "max_control_steps": 600, "output": str(output)},
                    indent=2,
                )
            )
        elif args.op == "check":
            print(json.dumps(resources(c), indent=2))
        else:
            if not args.live:
                raise ValueError("run requires explicit --live")
            lock_path = output.with_suffix(".lock")
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                run(c, output)


if __name__ == "__main__":
    main()
