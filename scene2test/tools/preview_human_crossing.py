"""Offline crossing trace with a synthetic base approach; no policy, GPU or API."""

import argparse
import json
from pathlib import Path

import mujoco

from clear_path import fixture
from clear_path.contracts import CrossingHumanFixture
from clear_path.human_motion import HumanCrossing
from clear_path.humans import human_scene
from robot_vlm.scene_config import validate_scene


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    config = validate_scene(json.loads(args.scene_config.read_text()))
    if not isinstance(config, CrossingHumanFixture):
        parser.error("crossing-human-v6 scene required")
    xml = fixture.world_xml(config)
    model = mujoco.MjModel.from_xml_string(xml)
    if model.nmocap != 1:
        raise ValueError("expected one mocap human")
    motion = HumanCrossing(config)
    rows = []
    for i in range(701):
        t = i * 0.05
        base = [min(7.0, 1.0 + 0.2 * max(0.0, t - 2.0)), 0.0]
        rows.append(motion.sample(t, base, armed=t >= 2.0))
    summary = {
        "scene_config": config.model_dump(),
        "scene_revision": fixture.identity(config),
        "human_scene": human_scene(config),
        "trace_kind": "synthetic straight base approach at 0.2m/s after 2s; not G1 rollout",
        "model_xml_compiled": True,
        "samples": len(rows),
        "triggered_at_s": motion.triggered_at_s,
        "minimum_sampled_center_distance_m": min(r["center_distance_m"] for r in rows),
        "final_state": rows[-1]["state"],
        "robot_policy_calls": 0,
        "task_outcome": None,
        "eligible_for_family_coverage": False,
    }
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "initial_scene.xml").write_text(xml)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (args.output_dir / "synthetic_trace.jsonl").write_text(
        "".join(json.dumps(row, allow_nan=False) + "\n" for row in rows)
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
