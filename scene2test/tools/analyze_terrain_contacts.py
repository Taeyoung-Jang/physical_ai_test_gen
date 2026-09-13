"""Reconstruct contacts at saved poses; not a dynamics replay or original event log."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import mujoco
import numpy as np


def contact_record(model, contact, time_s):
    record = {
        "time_s": float(time_s),
        "position_m": contact.pos.tolist(),
        "normal_geom1_to_geom2": contact.frame[:3].tolist(),
        "distance_m": float(contact.dist),
    }
    for side in (1, 2):
        ident = int(getattr(contact, f"geom{side}"))
        body = int(model.geom_bodyid[ident])
        record.update(
            {
                f"geom{side}_id": ident,
                f"geom{side}": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, ident),
                f"body{side}_id": body,
                f"body{side}": mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_BODY, body),
            }
        )
    return record


def analyze(job, output):
    output.mkdir(parents=True, exist_ok=False)
    model_path = job / "composed_scene.xml"
    model = mujoco.MjModel.from_xml_path(str(model_path))
    data = mujoco.MjData(model)
    states = [json.loads(s) for s in (job / "state_trajectory.jsonl").read_text().splitlines()]
    counts, late_counts = Counter(), Counter()
    late_start = states[-1]["time_s"] - 10
    with (output / "reconstructed_contacts.jsonl").open("x") as stream:
        for state in states:
            data.qpos[:] = state["qpos"]
            data.qvel[:] = state["qvel"]
            data.time = state["time_s"]
            mujoco.mj_forward(model, data)
            for contact in data.contact:
                if contact.dist > 0:
                    continue
                row = contact_record(model, contact, data.time)
                names = [row[f"geom{i}"] or "" for i in (1, 2)]
                if not any(n.startswith("world_surface_") for n in names):
                    continue
                key = " / ".join(str(row[k]) for k in ("geom1", "body1", "geom2", "body2"))
                counts[key] += 1
                if data.time >= late_start:
                    late_counts[key] += 1
                stream.write(json.dumps(row) + "\n")
    late = [s for s in states if s["time_s"] >= late_start]
    summary = {
        "source_job": str(job.resolve()),
        "method": "mj_forward at saved qpos/qvel; sampled geometry only, not dynamics replay",
        "mujoco_version": mujoco.__version__,
        "analyzer_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "input_sha256": {
            name: hashlib.sha256((job / name).read_bytes()).hexdigest()
            for name in ("composed_scene.xml", "state_trajectory.jsonl")
        },
        "sample_count": len(states),
        "last_sample_time_s": states[-1]["time_s"],
        "late_window_start_s": late_start,
        "late_base_xyz_min": np.min([s["qpos"][:3] for s in late], axis=0).tolist(),
        "late_base_xyz_max": np.max([s["qpos"][:3] for s in late], axis=0).tolist(),
        "contact_counts": dict(counts),
        "late_contact_counts": dict(late_counts),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("jobs", nargs="+", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/workspace/g1_failure/runtime/terrain_diagnostics"),
    )
    args = parser.parse_args()
    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    for job in args.jobs:
        print(json.dumps(analyze(job, root / job.name)), flush=True)
    print(f"OUTPUT={root}", flush=True)


if __name__ == "__main__":
    main()
