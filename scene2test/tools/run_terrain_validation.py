"""Isolated sequential CUDA terrain validation. Does not modify or use server job queues."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from failure_client.contracts import RolloutRequest
from simulation_server.worlds import validate_bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--names", nargs="+")
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--speed", type=float, default=0.25)
    parser.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/terrain_validation")
    )
    parser.add_argument("--bundle", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--job", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.job:
        from simulation_server.terrain_worker import run_terrain

        request = RolloutRequest.model_validate_json((args.job / "request.json").read_text())
        result = run_terrain(request, args.job, args.groot_root, args.bundle)
        if result.reproduction["runtime"]["execution_provider"] != "CUDAExecutionProvider":
            raise RuntimeError("CUDA execution required")
        result.reproduction["execution_route"] = "isolated_terrain_runner"
        (args.job / "execution_result.json").write_text(result.model_dump_json(indent=2))
        return
    if args.suite is None or not 1 <= args.duration <= 600 or not 0.05 <= args.speed <= 0.4:
        parser.error("provide --suite; duration [1,600] and speed [.05,.4]")
    suite = json.loads(args.suite.read_text())
    scenes = [
        s
        for s in suite["scenes"]
        if s["status"] == "READY_FOR_TERRAIN_RUNNER"
        and (args.names is None or s["name"] in args.names)
    ]
    if not scenes:
        parser.error("no matching ready scenes")
    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"TERRAIN_RUN={root}", flush=True)
    asset = args.groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1"

    def ref(ident, path):
        return {"id": ident, "revision": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()}

    resources = {
        "robot": {**ref("unitree_g1_locomotion", asset / "g1_gear_wbc.xml"), "profile_id": "29dof"},
        "controller": ref("groot_locomotion", asset / "policy/GR00T-WholeBodyControl-Walk.onnx"),
        "policy": ref("groot_walk_policy", asset / "policy/GR00T-WholeBodyControl-Walk.onnx"),
    }
    (root / "protocol.json").write_text(
        json.dumps(
            {
                "suite": str(args.suite.resolve()),
                "duration_s": args.duration,
                "speed_mps": args.speed,
                "resources": resources,
                "scenes": scenes,
                "purpose": "terrain capability smoke; not AFS comparison",
            },
            indent=2,
        )
    )
    rows = []
    for scene in scenes:
        bundle = Path(scene["bundle"])
        spec = validate_bundle(bundle, "sha256:" + scene["revision"])
        if not hasattr(spec, "surfaces"):
            raise ValueError("terrain scenes only")
        job = root / ("job_" + uuid.uuid4().hex)
        job.mkdir()
        request = {
            "client_request_id": job.name,
            "research_context": {
                "experiment_id": root.name,
                "candidate_id": f"{scene['name']}_{scene['index']}",
                "method_instance_id": "terrain_smoke",
            },
            "resources": {
                **resources,
                "scene": {"id": spec.scene_id, "revision": "sha256:" + spec.revision},
            },
            "task": {"schema": "navigation@1.0", "parameters": {"speed_mps": args.speed}},
            "execution": {
                "seed": spec.config.seed,
                "maximum_duration_s": args.duration,
                "physics_timestep_s": 0.005,
                "settling_duration_s": 1.0,
            },
            "recording": {"video": "always"},
        }
        (job / "request.json").write_text(json.dumps(request, indent=2))
        print(f"{scene['name']}/{scene['index']} {job.name}", flush=True)
        start = time.monotonic()
        row = {
            "name": scene["name"],
            "index": scene["index"],
            "job": str(job),
            "status": "EXECUTION_ERROR",
        }
        env = {**os.environ, "MUJOCO_GL": "egl", "SIM_SERVER_ONNX_PROVIDER": "cuda"}
        with (job / "worker.log").open("w") as log:
            try:
                child = subprocess.run(
                    [
                        sys.executable,
                        str(Path(__file__).resolve()),
                        "--job",
                        str(job),
                        "--bundle",
                        str(bundle),
                        "--groot-root",
                        str(args.groot_root),
                    ],
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    timeout=args.duration + 240,
                )
                if child.returncode == 0:
                    result = json.loads((job / "execution_result.json").read_text())
                    row.update(
                        execution=result["execution"],
                        facts=result["task_facts"],
                        status="EVALUATED" if result["execution"]["valid"] else "INDETERMINATE",
                    )
                    for artifact in result["artifacts"]:
                        ident, name = artifact["artifact_id"].split(":", 1)
                        if ident != job.name or Path(name).name != name:
                            raise ValueError("unexpected artifact identity")
                        data = (job / name).read_bytes()
                        if (
                            hashlib.sha256(data).hexdigest()
                            != artifact["sha256"].removeprefix("sha256:")
                            or len(data) != artifact["size_bytes"]
                        ):
                            raise ValueError("artifact mismatch")
                    row["verified_artifacts"] = len(result["artifacts"])
                else:
                    row["exit_code"] = child.returncode
            except subprocess.TimeoutExpired:
                row["reason"] = "WORKER_TIMEOUT"
        row["wall_seconds"] = time.monotonic() - start
        rows.append(row)
        (root / "summary.json").write_text(json.dumps(rows, indent=2))
        print(
            json.dumps(
                {
                    "name": row["name"],
                    "status": row["status"],
                    "reason": row.get("execution", {}).get("termination_reason"),
                }
            ),
            flush=True,
        )
    print(f"SUMMARY={root / 'summary.json'}", flush=True)
    if any(r["status"] != "EVALUATED" for r in rows):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
