"""Prepare/run three independent paired search sets for each of Object and Goal."""

import argparse
import copy
import fcntl
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
from robot_arm import placement, search  # noqa: E402
from robot_arm import task_comparison as experiment  # noqa: E402
from robot_arm import task_environments as envs  # noqa: E402

DEFAULT = PROJECT / "config/robot_arm_object_goal_comparison.json"
ROOT = PROJECT / "experiments/robot_arm_libero/object_goal_search_repetitions3_v1"
LAUNCHER = PROJECT / "tools/run_robot_arm_object_goal_comparisons.sh"


def config(path):
    c = search.read(path)
    if c["version"] != experiment.VERSION or set(c["tasks"]) != {"object", "goal"}:
        raise ValueError("wrong two-task bundle")
    used = set()
    for task, designs in c["tasks"].items():
        if len(designs) != 3:
            raise ValueError("three repetitions required per task")
        normalized = []
        for d in designs:
            experiment.validate(d)
            if d["task"] != task or used.intersection(d["seeds"]):
                raise ValueError("wrong task/reused seed")
            used.update(d["seeds"])
            other = copy.deepcopy(d)
            other.pop("seeds")
            normalized.append(other)
        if any(d != normalized[0] for d in normalized[1:]):
            raise ValueError("repetitions differ in conditions")
    return c


def sources(d):
    upstream = Path(d["robot"]["upstream_root"])
    paths = [
        Path(__file__).resolve(),
        LAUNCHER,
        PROJECT / "src/robot_arm/task_comparison.py",
        PROJECT / "src/robot_arm/task_environments.py",
        PROJECT / "src/robot_arm/free_pair_search.py",
        PROJECT / "src/robot_arm/free_pair_obstacles.py",
        PROJECT / "src/robot_arm/capability.py",
        PROJECT / "src/robot_arm/placement.py",
        PROJECT / "src/robot_arm/search.py",
        PROJECT / "src/robot_arm/openrouter.py",
        PROJECT / "src/robot_vlm/openrouter.py",
        PROJECT / "src/llm_afs/provider.py",
        Path(d["robot"]["libero_config_path"]) / "config.yaml",
    ]
    paths += sorted((upstream / "gr00t").rglob("*.py"))
    paths += sorted((upstream / "external_dependencies/LIBERO/libero").rglob("*.py"))
    # Bind native collision meshes and material definitions as well as the task predicate files.
    assets = upstream / "external_dependencies/LIBERO/libero/libero/assets"
    paths += sorted(p for p in assets.rglob("*") if p.is_file())
    suite, task = envs.TASKS[d["task"]]
    paths.append(
        upstream
        / "external_dependencies/LIBERO/libero/libero/bddl_files"
        / suite
        / (task + ".bddl")
    )
    return list(dict.fromkeys(paths))


def plan(c):
    return {
        "version": experiment.VERSION,
        "robot_attempt_cap": 144,
        "afs_request_cap": 36,
        "control_step_cap": 43200,
        "per_task": {
            task: {
                "sets": 3,
                "afs_episodes": 36,
                "random_episodes": 36,
                "search_seeds": [d["seeds"] for d in ds],
                "axes": ds[0]["domain"],
                "scenario_hypotheses": experiment.SCENARIOS[task],
            }
            for task, ds in c["tasks"].items()
        },
        "history": "Own task/set/seed/AFS only; no historical or other-arm outcomes imported",
        "design": "Each set: 3 search seeds x "
        "(2 common Uniform bootstrap + 2 later slots) per method",
        "executed": False,
    }


def planned(c):
    for task, designs in c["tasks"].items():
        for number, d in enumerate(designs, 1):
            for seed in d["seeds"]:
                for index in range(d["per_arm"]):
                    yield task, number, d, seed, index, experiment.uniform(d, seed, index)


def audit(c, output):
    """Native CPU compile/reset only: no camera, policy, action or API."""
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for task, designs in c["tasks"].items():
        robot = designs[0]["robot"]
        os.environ["LIBERO_CONFIG_PATH"] = robot["libero_config_path"]
        sys.path.insert(0, robot["upstream_root"])
        from libero.libero.envs.env_wrapper import ControlEnv

        bddl = next(p for p in sources(designs[0]) if p.suffix == ".bddl")
        control = ControlEnv(str(bddl), use_camera_obs=False, has_offscreen_renderer=False)
        try:
            for _, number, d, seed, index, p in (r for r in planned(c) if r[0] == task):
                control.env.set_xml_processor(lambda xml, p=p: envs.inject(xml, task, p))
                control.seed(d["background_seed"])
                control.env.reset()
                value = envs.apply(control, task, p)
                name = f"{task}_{number}_{seed}_{index}"
                (output / (name + ".xml")).write_text(control.sim.model.get_xml())
                rows.append(
                    {
                        "task": task,
                        "set": number,
                        "seed": seed,
                        "index": index,
                        "parameters": p,
                        "audit": value,
                    }
                )
                print("CPU_GEOMETRY", name, value["valid"], value["problems"], flush=True)
        finally:
            control.close()
    report = {
        "config": c,
        "records": rows,
        "resampled": 0,
        "policy_executed": False,
        "valid": sum(r["audit"]["valid"] for r in rows),
        "total": len(rows),
        "claim": "Planned Uniform geometry only; future AFS geometry and policy success unverified",
    }
    placement.save(output / "geometry_audit.json", report)
    print("AUDIT", report["valid"], "/", report["total"], flush=True)
    return report


def prepare(c, root, audit_root):
    if root.exists():
        raise FileExistsError("preserve existing prepared output")
    report = search.read(audit_root / "geometry_audit.json")
    expected = [(task, number, seed, index, p) for task, number, _, seed, index, p in planned(c)]
    actual = [
        (r["task"], r["set"], r["seed"], r["index"], r["parameters"]) for r in report["records"]
    ]
    if (
        report["config"] != c
        or actual != expected
        or not all(r["audit"]["valid"] for r in report["records"])
        or report["resampled"] != 0
        or report["policy_executed"]
    ):
        raise ValueError("all original planned geometry must pass before freezing")
    frozen_by_task = {}
    # Finish all hashing before creating the prepared root.
    for task, designs in c["tasks"].items():
        print("FREEZE", task, "sources/assets/model", flush=True)
        d = designs[0]
        frozen_by_task[task] = {
            "source_hashes": {str(p): search.sha(p) for p in sources(d)},
            "model_hashes": {
                str(p): search.sha(p)
                for p in sorted(Path(d["robot"]["model_path"]).glob("*"))
                if p.is_file()
            },
        }
    root.mkdir(parents=True, exist_ok=False)
    rows = []
    for task, designs in c["tasks"].items():
        for number, d in enumerate(designs, 1):
            child = root / task / f"set_{number}"
            child.mkdir(parents=True)
            placement.save(child / "manifest.json", {"design": d, **frozen_by_task[task]})
            sha = search.sha(child / "manifest.json")
            (child / "manifest.sha256").write_text(sha + "\n")
            rows.append(
                {
                    "task": task,
                    "set": number,
                    "directory": str(child.relative_to(root)),
                    "manifest_sha256": sha,
                }
            )
    bundle = {
        "config": c,
        "plan": plan(c),
        "sets": rows,
        "geometry_audit": {
            "path": str((audit_root / "geometry_audit.json").resolve()),
            "sha256": search.sha(audit_root / "geometry_audit.json"),
        },
    }
    placement.save(root / "bundle.json", bundle)
    (root / "bundle.sha256").write_text(search.sha(root / "bundle.json") + "\n")
    return bundle


def bundle_for(root):
    if (root / "bundle.sha256").read_text().strip() != search.sha(root / "bundle.json"):
        raise ValueError("bundle changed")
    bundle = search.read(root / "bundle.json")
    c = bundle["config"]
    if bundle["plan"] != plan(c):
        raise ValueError("plan/config mismatch")
    if len(bundle["sets"]) != 6:
        raise ValueError("six independent sets required")
    for row in bundle["sets"]:
        child = root / row["directory"]
        if (
            not child.resolve().is_relative_to(root.resolve())
            or search.sha(child / "manifest.json") != row["manifest_sha256"]
        ):
            raise ValueError("child manifest changed")
        d = experiment.verify(child, files=False)
        if d != c["tasks"][row["task"]][row["set"] - 1]:
            raise ValueError("child/config mismatch")
    return bundle


def atomic(path, value):
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        temp = stream.name
    os.replace(temp, path)


def report(root):
    bundle = bundle_for(root)
    tasks = {}
    lines = ["Object / Goal AFS vs Random: independent 3-set development comparison"]
    for task in ("object", "goal"):
        rows = [
            {**r, "summary": experiment.summary(root / r["directory"])}
            for r in bundle["sets"]
            if r["task"] == task
        ]
        complete = all(r["summary"]["complete"] for r in rows)
        aggregate = None
        if complete:
            aggregate = {}
            for method in ("afs", "random"):
                rates = [100 * r["summary"]["totals"][method]["valid_failure_rate"] for r in rows]
                aggregate[method] = {
                    "per_set_percent": rates,
                    "mean_percent": statistics.mean(rates),
                    "sample_sd_percentage_points": statistics.stdev(rates),
                }
            differences = [r["summary"]["difference_percentage_points"] for r in rows]
            aggregate["paired_difference"] = {
                "mean_percentage_points": statistics.mean(differences),
                "sample_sd_percentage_points": statistics.stdev(differences),
            }
        tasks[task] = {"complete": complete, "sets": rows, "aggregate": aggregate}
        for row in rows:
            totals = row["summary"]["totals"]
            lines.append(
                f"{task} set{row['set']}: "
                + " | ".join(
                    f"{method}: FAIL{t['fail']} PASS{t['pass']} valid{t['valid']}/12 "
                    f"excluded{t['excluded']} pending{t['pending']} AFSreq{t['afs_requests']}"
                    for method, t in totals.items()
                )
            )
        if aggregate:
            for method in ("afs", "random"):
                value = aggregate[method]
                lines.append(
                    f"{task} {method}: {value['mean_percent']:.2f}% +/- sampleSD "
                    f"{value['sample_sd_percentage_points']:.2f}pp"
                )
            diff = aggregate["paired_difference"]
            lines.append(
                f"{task} AFS-Random: {diff['mean_percentage_points']:.2f}pp +/- sampleSD "
                f"{diff['sample_sd_percentage_points']:.2f}pp"
            )
        else:
            lines.append(task + ": incomplete; no aggregate mean/SD yet")
    result = {
        "tasks": tasks,
        "complete": all(t["complete"] for t in tasks.values()),
        "statistical_superiority_established": False,
        "scope": "Task-specific development domains; failures not causal families; "
        "native task failure separate from contact",
    }
    atomic(root / "replication_summary.json", result)
    (root / "replication_summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines), flush=True)
    return result


def worker(folder):
    root = folder.parents[2]
    d = experiment.verify(root)
    value = search.read(folder / "candidate.json")
    seed, index = int(folder.parents[1].name.split("_")[1]), int(folder.name.split("_")[1])
    if (
        seed not in d["seeds"]
        or not 0 <= index < d["per_arm"]
        or folder.parent.name not in d["methods"]
    ):
        raise ValueError("worker slot outside frozen budget")
    if (
        value != experiment.candidate(d, value["parameters"], seed, index, value["hypothesis"])
        or search.read(folder / "robot_intent.json") != value
    ):
        raise ValueError("candidate/domain/intent mismatch")
    placement.save(folder / "worker_started.json", {"pid": os.getpid()})
    try:
        result = envs.run_episode(d, value, folder)
    except Exception:
        import traceback

        traceback.print_exc()
        result = {
            "status": "INCONCLUSIVE",
            "task_outcome": None,
            "reason": "worker_execution_or_initial_geometry_error",
        }
    placement.save(folder / "receipt.json", result)
    placement.save(folder / "measurement.json", envs.measure(folder, result, d["task"]))
    experiment.seal(folder)
    return 0 if result["status"] == "VALID" else 1


def runner(d, value, folder):
    print("ROBOT_START", d["task"], folder, flush=True)
    command = [
        d["robot"]["python"],
        "-u",
        str(Path(__file__).resolve()),
        "_worker",
        "--output",
        str(folder),
    ]
    with (folder / "run.log").open("x") as log:
        child = subprocess.Popen(
            command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        try:
            while child.poll() is None:
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    print("HEARTBEAT", d["task"], str(folder / "run.log"), flush=True)
        except BaseException:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait(timeout=10)
            raise
    if child.returncode or not (folder / "evidence_manifest.json").exists():
        raise RuntimeError("worker stopped; no replay/replacement")
    print("ROBOT_RESULT", search.read(folder / "receipt.json"), flush=True)


def execute(root):
    from robot_arm.openrouter import call, require_key

    bundle = bundle_for(root)
    # Completed invocations are read-only and require no credentials.
    if report(root)["complete"]:
        return
    require_key()
    for row in bundle["sets"]:
        print("VERIFY", row["directory"], flush=True)
        experiment.verify(root / row["directory"])
    errors = []
    for row in bundle["sets"]:
        child = root / row["directory"]
        try:
            experiment.run(child, runner, lambda body: call(body, timeout=300), 24)
        except KeyboardInterrupt:
            report(root)
            raise
        except Exception as exc:
            errors.append({"set": row["directory"], "error": str(exc)})
            print("STOPPED_SET", row["directory"], str(exc), flush=True)
        report(root)
    if errors or not report(root)["complete"]:
        raise RuntimeError(
            "incomplete sets preserved; no retries/replacements: " + json.dumps(errors)
        )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "op",
        choices=["plan", "audit", "prepare", "status", "run", "_worker"],
        nargs="?",
        default="plan",
    )
    p.add_argument("--config", type=Path, default=DEFAULT)
    p.add_argument("--output", type=Path, default=ROOT)
    p.add_argument(
        "--audit-root", type=Path, default=PROJECT / "development/object_goal_geometry_20261024_v2"
    )
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    root = args.output.resolve()
    if args.op == "_worker":
        return worker(root)
    if args.op == "status":
        report(root)
    elif args.op == "run":
        if not args.live:
            raise ValueError("explicit --live required")

        def terminate(signum, frame):
            raise KeyboardInterrupt("requested termination")

        signal.signal(signal.SIGTERM, terminate)
        with (root / ".run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            execute(root)
    else:
        c = config(args.config)
        if args.op == "plan":
            print(json.dumps(plan(c), indent=2))
        elif args.op == "audit":
            audit(c, args.audit_root.resolve())
        else:
            prepare(c, root, args.audit_root.resolve())
            report(root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
