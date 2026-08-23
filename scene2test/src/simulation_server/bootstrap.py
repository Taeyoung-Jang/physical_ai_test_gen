from __future__ import annotations

import hashlib
import json

from .config import ServerConfig


def bootstrap_groot_registry(config: ServerConfig) -> None:
    """Register the pinned local GR00T resources without mutating existing manifests."""
    source = config.groot_root / "decoupled_wbc/control/robot_model/model_data/g1/scene_43dof.xml"
    if not source.is_file():
        return
    revision = f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"
    resources = {
        "scenes/g1_ground.json": {
            "id": "g1_ground",
            "revision": revision,
            "status": "READY",
            "backend": {"mjcf": str(source.relative_to(config.groot_root))},
            "snapshot": {
                "coordinate_system": {"up_axis": "Z", "unit": "meter"},
                "bounds": {"minimum_m": [-10, -10, -0.1], "maximum_m": [10, 10, 4]},
                "spawn_points": [{"id": "default", "position_m": [0, 0, 0.8]}],
                "query_capabilities": ["get_scene_summary", "list_objects"],
                "intervention_capabilities": ["set_robot_spawn"],
            },
        },
        "robots/unitree_g1.json": {
            "id": "unitree_g1",
            "revision": revision,
            "status": "READY",
            "compatibility": {"profile_ids": ["43dof"]},
        },
        "controllers/mock_standing.json": {
            "id": "mock_standing",
            "revision": "builtin:pd-standing-v1",
            "status": "READY",
        },
        "policies/hold_pose.json": {
            "id": "hold_pose",
            "revision": "builtin:hold-pose-v1",
            "status": "READY",
        },
        "tasks/stand.json": {"id": "stand", "revision": "schema:stand@1.0", "status": "READY"},
    }
    for relative, payload in resources.items():
        path = config.data_root / "registries" / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
