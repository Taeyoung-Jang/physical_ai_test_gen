"""Equal-valid-budget G1 scene-search pilot over the existing HTTP navigation server.

Resume with --resume RUN_DIRECTORY. Journal before submission plus idempotency keys
prevents duplicate simulation after interruption. Keep one runner per directory.
"""

import argparse
import fcntl
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx

from procedural_world.export import export_bundle
from procedural_world.navigation_stages import stage_world
from procedural_world.search import (
    BOUNDS,
    VERSION,
    InvalidScene,
    SceneSearch,
    move_obstacle,
    outcome,
)
from simulation_server.worlds import register_world


def save(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n")
    temporary.replace(path)


def report(run, protocol, rows):
    summaries = {}
    for method in protocol["methods"]:
        group = [r for r in rows if r["method"] == method]
        valid = [r for r in group if r.get("evaluation") is not None]
        failures = [i + 1 for i, r in enumerate(valid) if r["evaluation"]["failure"]]
        summaries[method] = {
            "attempts": len(group),
            "valid_rollouts": len(valid),
            "failures": len(failures),
            "failure_rate": len(failures) / len(valid) if valid else None,
            "first_failure_valid_index": failures[0] if failures else None,
            "adaptive_rollouts": sum(r["proposal"]["phase"] == "adaptive" for r in valid),
            "statuses": dict(Counter(r["status"] for r in group)),
            "wall_seconds": sum(r.get("wall_seconds", 0) for r in group),
            "complete": len(valid) == protocol["valid_budget"],
        }
    summary = {
        "protocol": protocol,
        "methods": summaries,
        "complete": all(s["complete"] for s in summaries.values()),
    }
    save(run / "summary.json", summary)
    lines = [
        "# G1 Scene Search pilot",
        "",
        "Single seed; exploratory evidence, not proof of AFS superiority.",
        "",
        "| Method | Valid | Failures | Invalid scenes | Execution errors | Adaptive valid |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for m, s in summaries.items():
        lines.append(
            f"| {m} | {s['valid_rollouts']} | {s['failures']} | "
            f"{s['statuses'].get('INVALID_SCENE', 0)} | "
            f"{s['statuses'].get('EXECUTION_ERROR', 0)} | {s['adaptive_rollouts']} |"
        )
    lines.extend(
        [
            "",
            f"Complete: {summary['complete']}",
            "",
            "Per-attempt request, scene revision, result and verified artifacts are in attempts/.",
        ]
    )
    (run / "report.md").write_text("\n".join(lines) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--data-root", type=Path, default=Path("/workspace/g1_failure/runtime/navigation_server")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/scene_search")
    )
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--valid-budget", type=int, default=8)
    parser.add_argument("--max-attempts", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260906)
    args = parser.parse_args()
    if args.valid_budget < 5 or args.max_attempts < args.valid_budget:
        parser.error("budget must be >=5 (4 cold-start + adaptive); attempts >= budget")
    run = args.resume or args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    run.mkdir(parents=True, exist_ok=bool(args.resume))
    lock = (run / "runner.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    print(f"RUN_DIRECTORY={run}", flush=True)
    base = stage_world("obstacle")
    headers = (
        {"Authorization": "Bearer " + os.environ["SIM_SERVER_API_KEY"]}
        if os.getenv("SIM_SERVER_API_KEY")
        else {}
    )
    with httpx.Client(base_url=args.url, headers=headers, timeout=60) as client:
        registry_response = client.get("/api/v1/registry/snapshot")
        registry_response.raise_for_status()
        registry = registry_response.json()

        def ref(kind, ident):
            entry = next(e for e in registry[kind] if e["id"] == ident)
            return {"id": ident, "revision": entry["revision"]}

        resources = {
            "robot": {**ref("robots", "unitree_g1_locomotion"), "profile_id": "29dof"},
            "controller": ref("controllers", "groot_locomotion"),
            "policy": ref("policies", "groot_walk_policy"),
        }
        source = Path(__file__).resolve().parents[1] / "src"
        code_paths = [
            Path(__file__),
            source / "procedural_world/search.py",
            source / "procedural_world/core.py",
            source / "procedural_world/navigation_stages.py",
        ]
        code_paths += [
            source / "simulation_server" / n
            for n in ("navigation_worker.py", "navigation.py", "worlds.py", "groot_locomotion.py")
        ]
        hashes = {
            str(p.relative_to(source.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in code_paths
        }
        if args.resume:
            protocol = json.loads((run / "protocol.json").read_text())
            if (
                protocol["code_sha256"] != hashes
                or protocol["resources"] != resources
                or protocol["base_revision"] != base.revision
            ):
                raise RuntimeError("code/resource/base revision changed; create a new experiment")
            if protocol["url"] != args.url or protocol["data_root"] != str(
                args.data_root.resolve()
            ):
                raise RuntimeError("resume must use original server and data root")
            rows = json.loads((run / "journal.json").read_text())
        else:
            protocol = {
                "version": VERSION,
                "methods": ["random", "sobol", "afs"],
                "seed": args.seed,
                "valid_budget": args.valid_budget,
                "max_attempts": args.max_attempts,
                "duration_s": 120.0,
                "speed_mps": 0.3,
                "cold_start": 4,
                "bounds_m": BOUNDS.tolist(),
                "object_id": "obstacle_0",
                "base_revision": base.revision,
                "resources": resources,
                "url": args.url,
                "data_root": str(args.data_root.resolve()),
                "code_sha256": hashes,
                "failure_definition": "valid navigation_success == false",
                "utility_version": VERSION,
                "observation": "ground_truth; recompute map for every scene",
                "recording": "always",
            }
            rows = []
            save(run / "protocol.json", protocol)
            save(run / "journal.json", rows)
        # Sequential by method; timing is reported but not a randomized wall-time comparison.
        for method in protocol["methods"]:
            search = SceneSearch(method, protocol["seed"], protocol["cold_start"])
            while True:
                group = [r for r in rows if r["method"] == method]
                pending = next((r for r in group if r["status"] == "PENDING"), None)
                if pending is None:
                    if (
                        sum(r.get("evaluation") is not None for r in group)
                        >= protocol["valid_budget"]
                        or len(group) >= protocol["max_attempts"]
                    ):
                        break
                    offsets, proposal = search.propose(group)
                    row = {
                        "method": method,
                        "attempt": len(group),
                        "offsets": offsets,
                        "proposal": proposal,
                        "status": "PENDING",
                        "evaluation": None,
                    }
                    rows.append(row)
                    save(run / "journal.json", rows)
                else:
                    row = pending
                folder = run / "attempts" / f"{method}_{row['attempt']:04d}"
                folder.mkdir(parents=True, exist_ok=True)
                started = time.monotonic()
                try:
                    spec = move_obstacle(base, row["offsets"])
                except InvalidScene as exc:
                    row.update(status="INVALID_SCENE", rejection=str(exc))
                    save(folder / "mutation.json", row)
                    save(run / "journal.json", rows)
                    report(run, protocol, rows)
                    continue
                row["derived_revision"] = spec.revision
                bundle = folder / "worlds" / spec.scene_id
                if not bundle.exists():
                    bundle = export_bundle(spec, folder / "worlds")
                scene = register_world(bundle, args.data_root)
                request = {
                    "client_request_id": f"{run.name}_{method}_{row['attempt']}",
                    "research_context": {
                        "experiment_id": run.name,
                        "candidate_id": folder.name,
                        "method_instance_id": method,
                    },
                    "resources": {
                        **resources,
                        "scene": {"id": scene["id"], "revision": scene["revision"]},
                    },
                    "task": {
                        "schema": "navigation@1.0",
                        "parameters": {"speed_mps": protocol["speed_mps"]},
                    },
                    "execution": {
                        "seed": protocol["seed"],
                        "maximum_duration_s": protocol["duration_s"],
                        "physics_timestep_s": 0.005,
                        "settling_duration_s": 1.0,
                    },
                    "recording": {"video": "always"},
                }
                save(folder / "request.json", request)
                save(
                    folder / "mutation.json",
                    {
                        "base_revision": base.revision,
                        "derived_revision": spec.revision,
                        "offsets": row["offsets"],
                        "object_id": "obstacle_0",
                    },
                )
                if "job_id" not in row:
                    response = client.post(
                        "/api/v1/rollouts",
                        json=request,
                        headers={"Idempotency-Key": request["client_request_id"]},
                    )
                    response.raise_for_status()
                    row["job_id"] = response.json()["job_id"]
                    save(run / "journal.json", rows)
                job = row["job_id"]
                print(
                    f"{method} attempt={row['attempt']} {row['proposal']['phase']} job={job}",
                    flush=True,
                )
                deadline = time.monotonic() + protocol["duration_s"] + 360
                while True:
                    response = client.get(f"/api/v1/rollouts/{job}")
                    response.raise_for_status()
                    if response.json()["status"] in {
                        "SUCCEEDED",
                        "FAILED",
                        "CANCELLED",
                        "INTERRUPTED",
                    }:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError(
                            f"{job} still active; saved pending state, not cancelled"
                        )
                    time.sleep(2)
                response = client.get(f"/api/v1/rollouts/{job}/result")
                response.raise_for_status()
                result = response.json()
                save(folder / "result.json", result)
                verified = []
                for artifact in result.get("artifacts", []):
                    # Server artifact URI is relative to this authenticated server.
                    uri = "/api/v1/artifacts/" + artifact["artifact_id"]
                    response = client.get(uri)
                    response.raise_for_status()
                    digest = hashlib.sha256(response.content).hexdigest()
                    if (
                        digest != artifact["sha256"].removeprefix("sha256:")
                        or len(response.content) != artifact["size_bytes"]
                    ):
                        raise RuntimeError("artifact checksum mismatch")
                    verified.append({"uri": uri, "sha256": digest, "bytes": len(response.content)})
                save(folder / "verified_artifacts.json", verified)
                evaluation = outcome(result, protocol["duration_s"])
                if evaluation is not None:
                    reproduction = result["reproduction"]
                    if (
                        reproduction["runtime"]["execution_provider"] != "CUDAExecutionProvider"
                        or reproduction["scene_revision"] != spec.revision
                    ):
                        raise RuntimeError("execution did not match CUDA/scene protocol")
                row.update(
                    status="EVALUATED" if evaluation is not None else "EXECUTION_ERROR",
                    evaluation=evaluation,
                    termination_reason=result["execution"]["termination_reason"],
                    wall_seconds=time.monotonic() - started,
                )
                save(run / "journal.json", rows)
                summary = report(run, protocol, rows)
                print(json.dumps({"method": method, **summary["methods"][method]}), flush=True)
        summary = report(run, protocol, rows)
        print(f"REPORT={run / 'report.md'} COMPLETE={summary['complete']}", flush=True)
        if not summary["complete"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
