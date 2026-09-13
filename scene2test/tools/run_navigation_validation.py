"""Sequential HTTP validation; saves all attempts without overwriting evidence."""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from procedural_world.core import navigation_map
from procedural_world.export import export_bundle
from procedural_world.navigation_stages import stage_world
from simulation_server.worlds import register_world


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument(
        "--data-root", type=Path, default=Path("/workspace/g1_failure/runtime/navigation_server")
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/workspace/g1_failure/runtime/navigation_validation"),
    )
    parser.add_argument(
        "--stages", nargs="+", default=["straight", "corner", "obstacle", "rooms", "maze"]
    )
    parser.add_argument("--speed", type=float, default=0.3)
    parser.add_argument("--no-video", action="store_true")
    args = parser.parse_args()
    run = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    run.mkdir(parents=True, exist_ok=False)
    print(f"RUN_DIRECTORY={run}", flush=True)
    headers = (
        {"Authorization": "Bearer " + os.environ["SIM_SERVER_API_KEY"]}
        if os.getenv("SIM_SERVER_API_KEY")
        else {}
    )
    with httpx.Client(base_url=args.url, headers=headers, timeout=60) as client:
        rows = []
        for stage in args.stages:
            spec = stage_world(stage)
            bundle = export_bundle(spec, run / "worlds")
            scene = register_world(bundle, args.data_root)
            response = client.get("/api/v1/registry/snapshot")
            response.raise_for_status()
            registry = response.json()

            def ref(kind, ident):
                entry = next(e for e in registry[kind] if e["id"] == ident)
                return {"id": ident, "revision": entry["revision"]}

            duration = min(
                580.0, max(60.0, navigation_map(spec)["path_length_m"] / args.speed * 1.7 + 30)
            )
            request = {
                "client_request_id": f"{run.name}_{stage}",
                "research_context": {
                    "experiment_id": run.name,
                    "candidate_id": stage,
                    "method_instance_id": "gt_navigation_validation",
                },
                "resources": {
                    "scene": {"id": scene["id"], "revision": scene["revision"]},
                    "robot": {**ref("robots", "unitree_g1_locomotion"), "profile_id": "29dof"},
                    "controller": ref("controllers", "groot_locomotion"),
                    "policy": ref("policies", "groot_walk_policy"),
                },
                "task": {"schema": "navigation@1.0", "parameters": {"speed_mps": args.speed}},
                "execution": {
                    "seed": spec.config.seed,
                    "maximum_duration_s": duration,
                    "physics_timestep_s": 0.005,
                    "settling_duration_s": 1.0,
                },
                "recording": {"video": "never" if args.no_video else "always"},
            }
            (run / f"{stage}_request.json").write_text(json.dumps(request, indent=2))
            response = client.post(
                "/api/v1/rollouts",
                json=request,
                headers={"Idempotency-Key": request["client_request_id"]},
            )
            if response.status_code != 202:
                raise RuntimeError(f"submit failed: {response.text}")
            job_id = response.json()["job_id"]
            print(f"{stage}: submitted {job_id}, max_sim_s={duration:.1f}", flush=True)
            deadline = time.monotonic() + duration + 300
            while True:
                status_response = client.get(f"/api/v1/rollouts/{job_id}")
                status_response.raise_for_status()
                status = status_response.json()["status"]
                if status in {"SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(f"job {job_id} still running; not cancelled")
                time.sleep(2)
            result_response = client.get(f"/api/v1/rollouts/{job_id}/result")
            result_response.raise_for_status()
            result = result_response.json()
            (run / f"{stage}_result.json").write_text(json.dumps(result, indent=2))
            row = {
                "stage": stage,
                "job_id": job_id,
                "execution": result["execution"],
                "facts": result["task_facts"],
                "artifacts": result["artifacts"],
            }
            rows.append(row)
            (run / "summary.json").write_text(json.dumps(rows, indent=2))
            print(
                json.dumps(
                    {
                        "stage": stage,
                        "job": job_id,
                        "reason": result["execution"]["termination_reason"],
                        "success": result["task_facts"].get("navigation_success"),
                        "goal_distance": result["task_facts"].get("goal_distance_m"),
                    }
                ),
                flush=True,
            )
    print(f"SUMMARY={run / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
