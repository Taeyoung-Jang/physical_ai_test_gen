"""Independent CUDA diagnostic replay, checking trajectory agreement with saved samples.

Does not modify or dispatch the shared worker. Runs to the original termination time,
without rendering, and records identified contacts at that time and the first nonfoot
support collision. A match is evidence for these saved episodes, not determinism proof.
"""

import argparse
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import mujoco
import numpy as np
from analyze_terrain_contacts import contact_record

from simulation_server.groot_locomotion import G1OnnxController
from simulation_server.navigation import Follower
from simulation_server.terrain_metrics import TerrainMetrics
from simulation_server.worker import _quaternion_rpy
from simulation_server.worlds import load_spec


def replay(job, output, groot_root):
    output.mkdir(parents=True, exist_ok=False)
    request = json.loads((job / "request.json").read_text())
    original = json.loads((job / "execution_result.json").read_text())
    model = mujoco.MjModel.from_xml_path(str(job / "composed_scene.xml"))
    spec = load_spec(job / "scene_spec.json")
    nav = json.loads((job / "navigation_map.json").read_text())
    params = request["task"]["parameters"]
    follower = Follower(
        nav,
        params.get("speed_mps", 0.3),
        params.get("goal_tolerance_m", 0.25),
        boxes=spec.boxes,
        terrain_spec=spec,
    )
    controller = G1OnnxController(groot_root, "walk", np.zeros(3), model=model)
    if controller.execution_provider != "CUDAExecutionProvider":
        raise RuntimeError("CUDA required")
    data = controller.data
    model.opt.timestep = request["execution"]["physics_timestep_s"]
    data.qpos[:2] = spec.spawn_xy
    from procedural_world.terrain import ground_height

    data.qpos[2] += ground_height(spec, spec.spawn_xy)
    heading = math.atan2(*(follower.path[1] - follower.path[0])[::-1])
    data.qpos[3:7] = [math.cos(heading / 2), 0, 0, math.sin(heading / 2)]
    mujoco.mj_forward(model, data)
    metrics = TerrainMetrics(spec, model)
    samples = {
        round(s["time_s"] / model.opt.timestep): s
        for s in map(json.loads, (job / "state_trajectory.jsonl").read_text().splitlines())
    }
    end = original["task_facts"]["elapsed_simulation_s"]
    max_error, matched, first_collision = 0.0, 0, None
    final_contacts = []
    for step in range(1, round(end / model.opt.timestep) + 1):
        yaw = _quaternion_rpy(data.qpos[3:7])[2]
        controller.command = (
            np.zeros(3)
            if data.time < request["execution"]["settling_duration_s"]
            else follower.command(data.qpos[:2], yaw)
        )
        controller.step()
        mujoco.mj_forward(model, data)
        if step in samples:
            max_error = max(max_error, float(np.max(np.abs(data.qpos - samples[step]["qpos"]))))
            matched += 1
        contacts = [
            contact_record(model, c, data.time)
            for c in data.contact
            if c.dist <= 0 and metrics.nonfoot_collision(c)
        ]
        if contacts and first_collision is None:
            first_collision = contacts
        final_contacts = [contact_record(model, c, data.time) for c in data.contact if c.dist <= 0]
    report = {
        "source_job": str(job.resolve()),
        "execution_provider": controller.execution_provider,
        "method": "independent unrendered replay to original termination time",
        "mujoco_version": mujoco.__version__,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_sha256": {
            n: hashlib.sha256((job / n).read_bytes()).hexdigest()
            for n in ("composed_scene.xml", "request.json", "state_trajectory.jsonl")
        },
        "compared_samples": matched,
        "expected_samples": len(samples),
        "maximum_qpos_abs_error": max_error,
        "original_reason": original["execution"]["termination_reason"],
        "time_s": data.time,
        "final_xyz": data.qpos[:3].tolist(),
        "first_nonfoot_support_collision": first_collision,
        "final_contacts": final_contacts,
    }
    (output / "diagnostic.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", type=Path)
    parser.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/workspace/g1_failure/runtime/terrain_diagnostics"),
    )
    args = parser.parse_args()
    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    for job in args.jobs:
        replay(job, root / job.name, args.groot_root)
    print(f"OUTPUT={root}", flush=True)


if __name__ == "__main__":
    main()
