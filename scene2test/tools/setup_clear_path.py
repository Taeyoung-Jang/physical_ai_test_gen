"""Create an isolated dynamic fixture + G1 compatibility audit + visual report (P0/P1).

No GPT call, no policy inference, and no robot action execution.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/clear_path")
    )
    parser.add_argument(
        "--no-render", action="store_true", help="omit 3D previews, still create map/report"
    )
    args = parser.parse_args()
    os.environ.setdefault("MUJOCO_GL", "egl")
    import mujoco

    from clear_path import audit, contracts, fixture, report

    config = contracts.Fixture()
    source = args.groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    xml = fixture.world_xml(config, source)
    model = mujoco.MjModel.from_xml_string(xml)
    inspected = audit.inspect(source, model)
    initial = fixture.navigation_map(config)
    hypothetical = fixture.navigation_map(config, fixture.BOX_TARGET, hypothetical=True)
    if initial["reachable"] or not hypothetical["reachable"]:
        raise ValueError(
            "fixture must be initially blocked and geometrically open at hypothetical target"
        )
    root = args.output_root.resolve() / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"CLEAR_PATH_RUN={root}", flush=True)
    with (root / "scene.xml").open("x") as f:
        f.write(xml)
    for name, value in (
        ("config", config.model_dump()),
        ("robot_audit", inspected),
        ("scene_graph", fixture.graph(config)),
        ("map_initial", initial),
        ("map_hypothetical", hypothetical),
        ("action_schema", contracts.Action.model_json_schema()),
    ):
        write(root / f"{name}.json", value)
    data = audit.initial_data(model, source)
    cid = model.camera("clear_robot_camera").id
    write(
        root / "initial_state.json",
        {
            "state_version": 0,
            "time_s": 0,
            "scene_revision": fixture.identity(config),
            "frame": "world_m",
            "robot_pose": data.joint("floating_base_joint").qpos.tolist(),
            "box_pose": data.joint("clear_box_free").qpos.tolist(),
            "camera_world_position": data.cam_xpos[cid].tolist(),
            "camera_world_rotation": data.cam_xmat[cid].reshape(3, 3).tolist(),
            "camera_fovy_deg": float(model.cam_fovy[cid]),
            "image_size_hw": [540, 960],
            "enabled_actions": [],
            "robot_rollouts": 0,
        },
    )
    report.plot_map(initial, root / "map_initial.png")
    report.plot_map(hypothetical, root / "map_hypothetical.png")
    rendering = {"status": "SKIPPED"}
    if not args.no_render:
        try:
            rendering = {"status": "OK", **report.render(model, data, root)}
        except Exception as exc:
            rendering = {"status": "ERROR", "error_type": type(exc).__name__}
    status = {
        "stage": "P0_P1_FIXTURE",
        "status": "FIXTURE_READY" if rendering["status"] != "ERROR" else "PREVIEW_ERROR",
        "robot_rollouts": 0,
        "api_calls": 0,
        "push_executor_available": False,
        "initial_path_exists": initial["reachable"],
        "hypothetical_path_exists": hypothetical["reachable"],
        "rendering": rendering,
        "p0_control_integration": "PENDING_P2_PHYSICAL_VALIDATION",
    }
    write(root / "status.json", status)
    report.write_report(root, inspected, rendering)
    write(
        root / "protocol.json",
        {
            "schema_version": "clear-path-preparation-v1",
            "mujoco_version": mujoco.__version__,
            "scene_revision": fixture.identity(config),
            "code_sha256": {
                str(Path(m.__file__).name): audit.sha256(Path(m.__file__))
                for m in (audit, contracts, fixture, report)
            },
            "cli_sha256": audit.sha256(Path(__file__)),
            "robot_source": str(source.resolve()),
            "note": "scene.xml references external robot meshes; inspect robot_audit source hashes",
        },
    )
    write(
        root / "manifest.json",
        {
            "schema_version": "clear-path-artifacts-v1",
            "artifacts": [
                {"path": p.name, "sha256": audit.sha256(p), "size_bytes": p.stat().st_size}
                for p in sorted(root.iterdir())
                if p.is_file()
            ],
        },
    )
    print(
        f"REPORT={root / 'report.html'}; rendering={rendering['status']}; robot_rollouts=0",
        flush=True,
    )
    if rendering["status"] == "ERROR":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
