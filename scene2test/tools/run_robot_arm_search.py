"""Explicit-placement robot-arm development search. Default commands do not run a policy."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from robot_arm import placement, search  # noqa: E402

DEFAULT = PROJECT / "config/robot_arm_placement_comparison.json"


def sources(c):
    upstream = Path(c["robot"]["upstream_root"])
    paths = [
        Path(__file__).resolve(),
        PROJECT / "src/robot_arm/placement.py",
        PROJECT / "src/robot_arm/search.py",
        PROJECT / "src/llm_afs/provider.py",
        Path(c["robot"]["libero_config_path"]) / "config.yaml",
    ]
    if c.get("afs_api_provider") == "openrouter":
        paths += [PROJECT / "src/robot_arm/openrouter.py", PROJECT / "src/robot_vlm/openrouter.py"]
    paths += sorted((upstream / "gr00t").rglob("*.py"))
    paths += sorted((upstream / "external_dependencies/LIBERO/libero").rglob("*.py"))
    paths.append(
        upstream
        / "external_dependencies/LIBERO/libero/libero/bddl_files/libero_spatial"
        / (c["robot"]["env_name"].split("/")[1] + ".bddl")
    )
    return paths


def live_runner(c, candidate, directory):
    print("ROBOT_START", directory, flush=True)
    command = [
        c["robot"]["python"],
        str(Path(__file__).resolve()),
        "_worker",
        "--output",
        str(directory),
    ]
    with (directory / "run.log").open("x") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    receipt = directory / "receipt.json"
    if result.returncode or not receipt.is_file():
        return {
            "status": "INCONCLUSIVE",
            "task_outcome": None,
            "reason": "worker_error_or_missing_receipt",
            "returncode": result.returncode,
        }
    value = search.read(receipt)
    print("ROBOT_RESULT", value["task_outcome"], value.get("steps"), flush=True)
    return value


def worker(directory, manual=False):
    root = directory if manual else directory.parents[2]
    c = search.verify(root)
    candidate = search.read(directory / "candidate.json")
    placement.checked(candidate["positions"], c["bounds"])
    if search.read(directory / "robot_intent.json") != candidate:
        raise ValueError("robot intent/candidate mismatch")
    placement.save(directory / "worker_started.json", {"pid": os.getpid()})
    result = placement.run_episode(c, candidate, directory)
    placement.save(directory / "receipt.json", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "op",
        choices=[
            "plan",
            "init",
            "run",
            "status",
            "manual-init",
            "manual-run",
            "_worker",
            "_manual_worker",
            "audit",
        ],
    )
    parser.add_argument("--config", type=Path, default=DEFAULT)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "experiments/robot_arm_libero/placement_comparison_v1",
    )
    parser.add_argument("--positions", help="JSON object with bowl_x/y and plate_x/y in metres")
    parser.add_argument("--seed", type=int, default=61001)
    parser.add_argument("--max-new-attempts", type=int, default=1)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = args.output.resolve()
    if args.op in ("_worker", "_manual_worker"):
        worker(root, args.op == "_manual_worker")
        return
    if args.op == "status":
        print(json.dumps(search.summary(root), indent=2))
        return
    if args.op in ("plan", "init", "manual-init", "audit"):
        c = search.validate(search.read(args.config))
    else:
        if not args.live:
            raise ValueError("execution requires --live")
        c = search.verify(root)
    if args.op == "plan":
        n = len(c["seeds"]) * c["per_arm"] * 2
        print(
            json.dumps(
                {
                    "config": c,
                    "robot_attempt_cap": n,
                    "robot_step_cap": n * 300,
                    "afs_request_cap": len(c["seeds"]) * (c["per_arm"] - c["bootstrap"]),
                    "planned_random": [
                        {"seed": s, "index": i, "positions": search.uniform(c, s, i)}
                        for s in c["seeds"]
                        for i in range(c["per_arm"])
                    ],
                    "executed": False,
                },
                indent=2,
            )
        )
    elif args.op in ("init", "manual-init"):
        if root.exists():
            raise FileExistsError("output exists; preserve it")
        candidate = None
        if args.op == "manual-init":
            if not args.positions or not 0 <= args.seed < 100000000:
                raise ValueError("manual positions and nonnegative seed required")
            candidate = {
                "positions": placement.checked(json.loads(args.positions), c["bounds"]),
                "scene_seed": args.seed,
                "hypothesis": "operator specified",
            }
        manifest = search.freeze(c, sources(c))
        manifest["mode"] = "manual" if candidate else "paired_development"
        if candidate:
            manifest["manual_candidate"] = candidate
        root.mkdir(parents=True)
        placement.save(root / "manifest.json", manifest)
        (root / "manifest.sha256").write_text(search.sha(root / "manifest.json") + "\n")
        if candidate:
            placement.save(root / "candidate.json", candidate)
        print("PREPARED", root, "(no API/GPU/robot execution)")
    elif args.op == "run":
        if search.read(root / "manifest.json")["mode"] != "paired_development":
            raise ValueError("manual output is not a comparison")
        if not 1 <= args.max_new_attempts <= 24:
            raise ValueError("max-new-attempts must be 1..24")
        if c.get("afs_api_provider") == "openrouter":
            from robot_arm.openrouter import call, require_key

            require_key()  # Check before creating any new API or robot intent.
        else:
            from llm_afs.provider import call

        def propose(body):
            print("AFS_REQUEST", c["afs_model"], flush=True)
            return call(body, timeout=300)

        print(json.dumps(search.run(root, live_runner, propose, args.max_new_attempts), indent=2))
    elif args.op == "manual-run":
        if search.read(root / "manifest.json")["mode"] != "manual":
            raise ValueError("comparison output is not a manual probe")
        candidate = search.read(root / "candidate.json")
        if candidate != search.read(root / "manifest.json")["manual_candidate"]:
            raise ValueError("frozen manual candidate changed")
        placement.checked(candidate["positions"], c["bounds"])
        placement.save(root / "robot_intent.json", candidate)
        command = [
            c["robot"]["python"],
            str(Path(__file__).resolve()),
            "_manual_worker",
            "--output",
            str(root),
        ]
        with (root / "run.log").open("x") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode or not (root / "receipt.json").exists():
            raise RuntimeError("manual execution stopped; preserve logs; no automatic rerun")
        print(json.dumps(search.read(root / "receipt.json"), indent=2))
    else:
        # CPU simulator-only validation; no model, policy, rendering or episode steps.
        os.environ["LIBERO_CONFIG_PATH"] = c["robot"]["libero_config_path"]
        sys.path.insert(0, c["robot"]["upstream_root"])
        from libero.libero.envs.env_wrapper import ControlEnv

        task = [p for p in sources(c) if p.suffix == ".bddl"][0]
        env = ControlEnv(str(task), use_camera_obs=False, has_offscreen_renderer=False)
        records = []
        try:
            for seed in c["seeds"]:
                for index in range(c["per_arm"]):
                    env.seed(c["background_seed"])
                    env.env.reset()
                    row = placement.apply(
                        env, search.uniform(c, seed, index), c["background_positions"]
                    )
                    records.append({"seed": seed, "index": index, "audit": row})
        finally:
            env.close()
        root.mkdir(parents=True, exist_ok=False)
        placement.save(
            root / "geometry_audit.json",
            {
                "records": records,
                "policy_executed": False,
                "resampled": 0,
                "claim": "Initial geometry only; AFS future proposals not audited.",
            },
        )
        print("GEOMETRY_AUDIT", root, sum(r["audit"]["valid"] for r in records), "/", len(records))


if __name__ == "__main__":
    main()
