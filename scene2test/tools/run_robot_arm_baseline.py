"""Prepare a bounded external-policy baseline; no imports of GPU libraries in plan/check."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
DEFAULT = PROJECT / "config/robot_arm_libero_baseline.json"
SOURCES = [
    "gr00t/eval/rollout_policy.py",
    "gr00t/eval/_horizon_contract.py",
    "gr00t/eval/sim/LIBERO/libero_env.py",
    "gr00t/policy/gr00t_policy.py",
    "gr00t/eval/sim/wrapper/multistep_wrapper.py",
]


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path):
    c = json.loads(Path(path).read_text())
    if (
        c["schema_version"] != "robot-arm-libero-baseline-v1"
        or c["purpose"] != "development_baseline_not_afs_comparison"
        or c["afs_requests"] != 0
        or c["environment_changes"]
        or c["n_envs"] != 1
        or len(c["seeds"]) != 2
        or len(set(c["seeds"])) != 2
        or any(type(s) is not int or s < 0 for s in c["seeds"])
        or c["max_episode_steps"] != 300
        or c["n_action_steps"] != 8
        or c["suite"] != "libero_spatial"
        or c["env_name"]
        != "libero_sim/pick_up_the_black_bowl_from_table_center_and_place_it_on_the_plate"
    ):
        raise ValueError("unsupported baseline contract")
    return c


def plan(c, output):
    upstream = Path(c["upstream_root"])
    task = (
        upstream
        / "external_dependencies/LIBERO/libero/libero/bddl_files"
        / c["suite"]
        / (c["env_name"].split("/")[1] + ".bddl")
    )
    paths = [upstream / s for s in SOURCES] + [
        task,
        Path(__file__).resolve(),
        Path(c["libero_config_path"]) / "config.yaml",
    ]
    hashes = {str(p): digest(p) for p in paths if p.is_file()}
    commands = []
    for index, seed in enumerate(c["seeds"]):
        commands.append(
            [
                c["python"],
                str(Path(__file__).resolve()),
                "_worker",
                "--config",
                str(output / "config.json"),
                "--output",
                str(output),
                "--index",
                str(index),
            ]
        )
    return {
        "config": c,
        "source_hashes": hashes,
        "missing_sources": [str(p) for p in paths if not p.is_file()],
        "commands": commands,
        "episodes": 2,
        "robot_step_upper_bound": 600,
        "afs_connected": False,
        "outcomes": None,
        "note": "Seeded-reset development baseline, not a published benchmark reproduction.",
    }


def check(c):
    root = Path(c["model_path"])
    missing = []
    for name in ["config.json", "embodiment_id.json", "processor_config.json", "statistics.json"]:
        if not (root / name).is_file():
            missing.append(str(root / name))
    weights = sorted(root.glob("*.safetensors"))
    if not weights:
        missing.append(str(root / "*.safetensors"))
    index = root / "model.safetensors.index.json"
    if index.is_file():
        for name in set(json.loads(index.read_text())["weight_map"].values()):
            if not (root / name).is_file():
                missing.append(str(root / name))
    interpreter = Path(c["python"])
    dependencies = {"status": "interpreter_missing"}
    if interpreter.is_file():
        probe = subprocess.run(
            [
                str(interpreter),
                "-c",
                "import importlib.util,json; "
                'names=["gr00t","libero","torch","gymnasium","mujoco","tyro","transformers"]; '
                "print(json.dumps({x:importlib.util.find_spec(x) is not None for x in names}))",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        dependencies = {
            "returncode": probe.returncode,
            "stdout": probe.stdout.strip(),
            "stderr": probe.stderr[-2000:],
        }
    deps_ok = False
    try:
        deps_ok = dependencies.get("returncode") == 0 and all(
            json.loads(dependencies["stdout"]).values()
        )
    except (ValueError, KeyError):
        pass
    return {
        "local_resources_present": not missing and deps_ok,
        "ready_for_attempt": False if missing or not deps_ok else None,
        "backbone_access": {
            "model": "nvidia/Cosmos-Reason2-2B",
            "status": "UNVERIFIED",
            "action": "Approve model access on Hugging Face and authenticate in your terminal.",
        },
        "missing_model_files": missing,
        "dependencies": dependencies,
        "claim": "Presence checks only; GPU/runtime compatibility and baseline success unverified.",
    }


def execution_status(output):
    attempts = []
    for attempt in sorted(output.glob("attempt_*")):
        row = {"attempt": attempt.name, "log": str(attempt / "run.log")}
        for name in ("result.json", "exclusion.json"):
            if (attempt / name).is_file():
                row[name] = json.loads((attempt / name).read_text())
        log = attempt / "run.log"
        if log.is_file():
            content = log.read_text(errors="replace")
            if "GatedRepoError" in content and "nvidia/Cosmos-Reason2-2B" in content:
                row["diagnosis"] = "gated_backbone_access_denied"
                row["required_action"] = (
                    "Approve access at https://huggingface.co/nvidia/Cosmos-Reason2-2B "
                    "and run hf auth login in your terminal. "
                    "Preserve this run; do not delete intent."
                )
        attempts.append(row)
    return {
        "execution_intent_exists": (output / "execution_intent.json").exists(),
        "attempts": attempts,
        "automatic_resume": False,
    }


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2)
        f.write("\n")


def worker(c, output, index):
    """Internal entrypoint runs exactly one episode using the upstream policy."""
    frozen = json.loads((output / "plan.json").read_text())
    if c != frozen["config"]:
        raise ValueError("frozen configuration changed")
    for path, value in frozen["source_hashes"].items():
        if digest(path) != value:
            raise ValueError("frozen source changed: " + path)
    if index not in (0, 1):
        raise ValueError("invalid episode index")
    attempt = output / f"attempt_{index:05d}"
    # Parent creates intent before subprocess: failed/interrupted attempts are never resent.
    if not (attempt / "intent.json").is_file():
        raise ValueError("missing attempt intent")
    execution = json.loads((output / "execution_intent.json").read_text())
    for path, value in execution["model_hashes"].items():
        if digest(path) != value:
            raise ValueError("frozen checkpoint changed: " + path)
    write(attempt / "worker_started.json", {"pid": os.getpid()})
    os.environ["LIBERO_CONFIG_PATH"] = c["libero_config_path"]
    os.environ.setdefault("MUJOCO_GL", "egl")
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    sys.path.insert(0, c["upstream_root"])
    from gr00t.eval.rollout_policy import run_gr00t_sim_policy

    result = run_gr00t_sim_policy(
        env_name=c["env_name"],
        n_episodes=1,
        max_episode_steps=c["max_episode_steps"],
        model_path=c["model_path"],
        n_envs=1,
        n_action_steps=c["n_action_steps"],
        video_dir=str(attempt / "videos"),
        seed=c["seeds"][index],
    )
    successes = list(result[1])
    if len(successes) != 1:
        raise RuntimeError("missing/filtered episode outcome; do not count as robot FAIL")
    lengths = result[2].get("episode_lengths", [])
    write(
        attempt / "result.json",
        {
            "status": "VALID",
            "task_success": bool(successes[0]),
            "task_outcome": "PASS" if successes[0] else "FAIL",
            "seed": c["seeds"][index],
            "episode_lengths": [int(x) for x in lengths],
            "success_rule": "upstream LIBERO check_success via upstream rollout collector",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("op", choices=["plan", "check", "init", "run", "status", "_worker"])
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument(
        "--output", type=Path, default=PROJECT / "experiments/robot_arm_libero/baseline_v1"
    )
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--index", type=int)
    args = parser.parse_args()
    output = args.output.resolve()
    if args.op == "status":
        print(json.dumps(execution_status(output), indent=2))
        return
    if args.op == "run" and (output / "execution_intent.json").exists():
        print(json.dumps(execution_status(output), indent=2))
        raise SystemExit("Existing execution preserved. Use status; automatic rerun is disabled.")
    c = load(args.config)
    if args.op == "_worker":
        worker(c, output, args.index)
        return
    p = plan(c, output)
    if args.op == "plan":
        print(json.dumps(p, indent=2))
    elif args.op == "check":
        print(json.dumps(check(c), indent=2))
    elif args.op == "init":
        if p["missing_sources"]:
            raise ValueError("missing upstream sources")
        output.mkdir(parents=True, exist_ok=False)
        write(output / "config.json", c)
        write(output / "plan.json", p)
        write(output / "preflight.json", check(c))
        print("Prepared (not executed):", output)
    else:
        if not args.live:
            raise ValueError("run requires explicit --live")
        frozen = json.loads((output / "plan.json").read_text())
        if frozen != p:
            raise ValueError("frozen source/config changed; prepare a new version")
        if not check(c)["local_resources_present"]:
            raise ValueError("model or execution environment missing; use check")
        # Bind all local checkpoint files before spending any simulation steps.
        model_hashes = {
            str(f): digest(f) for f in sorted(Path(c["model_path"]).rglob("*")) if f.is_file()
        }
        write(
            output / "execution_intent.json",
            {
                "model_hashes": model_hashes,
                "note": "Single invocation; no automatic retries or resume after interruption.",
            },
        )
        for index, command in enumerate(p["commands"]):
            attempt = output / f"attempt_{index:05d}"
            attempt.mkdir()
            write(attempt / "intent.json", {"seed": c["seeds"][index], "command": command})
            with (attempt / "run.log").open("x") as log:
                completed = subprocess.run(
                    command, cwd=c["upstream_root"], stdout=log, stderr=subprocess.STDOUT
                )
            if completed.returncode or not (attempt / "result.json").is_file():
                write(
                    attempt / "exclusion.json",
                    {
                        "status": "INCONCLUSIVE",
                        "task_outcome": None,
                        "returncode": completed.returncode,
                        "reason": "worker_error_or_missing_outcome",
                    },
                )
                raise RuntimeError("execution stopped; preserve evidence; no retry or replacement")
        print("Baseline completed; see per-attempt result.json and videos.")


if __name__ == "__main__":
    main()
