"""Audit a completed scene-search journal and render its sampled mutation space."""

import argparse
import hashlib
import json
import platform
from importlib.metadata import version
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from procedural_world.search import SceneSearch, outcome


def review(run):
    protocol = json.loads((run / "protocol.json").read_text())
    rows = json.loads((run / "journal.json").read_text())
    if any(r["status"] == "PENDING" for r in rows):
        raise ValueError("run still has pending work; review after completion")
    output = run / "review"
    output.mkdir(exist_ok=False)
    audit = {
        "methods": {},
        "verified_local_artifacts": 0,
        "environment": {
            "python": platform.python_version(),
            **{
                name: version(name)
                for name in ("numpy", "scipy", "scikit-learn", "mujoco", "onnxruntime-gpu")
            },
        },
        "source_hashes_match": True,
        "sampler_replay_matches": True,
    }
    project = Path(__file__).resolve().parents[1]
    for name, expected in protocol["code_sha256"].items():
        if hashlib.sha256((project / name).read_bytes()).hexdigest() != expected:
            raise ValueError(f"source changed during experiment: {name}")
    fig, axes = plt.subplots(1, len(protocol["methods"]), figsize=(13, 4), sharex=True, sharey=True)
    for ax, method in zip(axes, protocol["methods"]):
        group = [r for r in rows if r["method"] == method]
        sampler = SceneSearch(method, protocol["seed"], protocol["cold_start"])
        facts = []
        videos = []
        for i, row in enumerate(group):
            point, metadata = sampler.propose(group[:i])
            if point != row["offsets"] or metadata != row["proposal"]:
                raise ValueError("journal does not reproduce deterministic sampler")
            valid = row["evaluation"] is not None
            color = (
                "tab:red"
                if valid and row["evaluation"]["failure"]
                else "tab:green"
                if valid
                else "gray"
            )
            ax.scatter(*row["offsets"], c=color, marker="o" if valid else "x")
            ax.annotate(
                str(i), row["offsets"], fontsize=7, xytext=(3, 3), textcoords="offset points"
            )
            if not valid:
                continue
            folder = run / "attempts" / f"{method}_{row['attempt']:04d}"
            result = json.loads((folder / "result.json").read_text())
            if row["evaluation"] != outcome(result, protocol["duration_s"]):
                raise ValueError("evaluation journal mismatch")
            rep = result["reproduction"]
            if (
                rep["scene_revision"] != row["derived_revision"]
                or rep["runtime"]["execution_provider"] != "CUDAExecutionProvider"
            ):
                raise ValueError("execution provenance mismatch")
            for name, actual in rep["code_sha256"].items():
                if actual != protocol["code_sha256"]["src/simulation_server/" + name]:
                    raise ValueError("worker code differs from frozen protocol")
            for artifact in result["artifacts"]:
                job, name = artifact["artifact_id"].split(":", 1)
                if job != row["job_id"] or Path(name).name != name:
                    raise ValueError("invalid artifact identity")
                path = Path(protocol["data_root"]) / "outputs/jobs" / job / name
                data = path.read_bytes()
                if (
                    hashlib.sha256(data).hexdigest() != artifact["sha256"].removeprefix("sha256:")
                    or len(data) != artifact["size_bytes"]
                ):
                    raise ValueError("local artifact verification failed")
                audit["verified_local_artifacts"] += 1
                if name == "rollout.mp4":
                    videos.append(str(path))
            facts.append(result["task_facts"])
        audit["methods"][method] = {
            "valid": len(facts),
            "failures": sum(not f["navigation_success"] for f in facts),
            "invalid_scenes": sum(r["status"] == "INVALID_SCENE" for r in group),
            "execution_errors": sum(r["status"] == "EXECUTION_ERROR" for r in group),
            "mean_elapsed_simulation_s": mean(f["elapsed_simulation_s"] for f in facts)
            if facts
            else None,
            "max_goal_distance_m": max((f["goal_distance_m"] for f in facts), default=None),
            "adaptive_valid": sum(
                r["evaluation"] is not None and r["proposal"]["phase"] == "adaptive" for r in group
            ),
            "videos": videos,
        }
        ax.set(
            title=method,
            xlabel="Obstacle X offset (m)",
            xlim=protocol["bounds_m"][0],
            ylim=protocol["bounds_m"][1],
        )
        ax.grid(alpha=0.2)
    axes[0].set_ylabel("Obstacle Y offset (m)")
    fig.suptitle("Green: success | Red: valid failure | Gray: excluded | Labels: proposal index")
    fig.tight_layout()
    fig.savefig(output / "mutation_space.png", dpi=160)
    plt.close(fig)
    audit["complete"] = all(
        s["valid"] == protocol["valid_budget"] for s in audit["methods"].values()
    )
    audit["common_cold_start_repeats"] = []
    baseline = {
        r["derived_revision"]: r
        for r in rows
        if r["method"] == "sobol" and r["evaluation"] is not None
    }
    for row in rows:
        if (
            row["method"] != "afs"
            or row["evaluation"] is None
            or row["proposal"]["phase"] != "cold_start"
        ):
            continue
        other = baseline.get(row["derived_revision"])
        if other is None:
            continue

        def facts_for(record):
            folder = run / "attempts" / f"{record['method']}_{record['attempt']:04d}"
            return json.loads((folder / "result.json").read_text())["task_facts"]

        a, b = facts_for(row), facts_for(other)
        audit["common_cold_start_repeats"].append(
            {
                "scene_revision": row["derived_revision"],
                "same_task_facts": a == b,
                "elapsed_difference_s": a["elapsed_simulation_s"] - b["elapsed_simulation_s"],
                "goal_distance_difference_m": a["goal_distance_m"] - b["goal_distance_m"],
            }
        )
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))
    return audit


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    review(args.run)
