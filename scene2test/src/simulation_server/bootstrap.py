from __future__ import annotations

import hashlib
import json

from .config import ServerConfig


def bootstrap_groot_registry(config: ServerConfig) -> None:
    """Register the pinned local GR00T resources without mutating existing manifests."""
    source = config.groot_root / "decoupled_wbc/control/robot_model/model_data/g1/scene_43dof.xml"
    locomotion_root = config.groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1"
    locomotion_source = locomotion_root / "g1_gear_wbc.xml"
    balance_policy = locomotion_root / "policy/GR00T-WholeBodyControl-Balance.onnx"
    walk_policy = locomotion_root / "policy/GR00T-WholeBodyControl-Walk.onnx"
    required = (source, locomotion_source, balance_policy, walk_policy)
    if not all(path.is_file() for path in required):
        return
    revision = f"sha256:{hashlib.sha256(source.read_bytes()).hexdigest()}"
    locomotion_revision = f"sha256:{hashlib.sha256(locomotion_source.read_bytes()).hexdigest()}"
    balance_revision = f"sha256:{hashlib.sha256(balance_policy.read_bytes()).hexdigest()}"
    walk_revision = f"sha256:{hashlib.sha256(walk_policy.read_bytes()).hexdigest()}"
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
        "scenes/g1_locomotion_ground.json": {
            "id": "g1_locomotion_ground",
            "revision": locomotion_revision,
            "status": "READY",
            "backend": {"mjcf": str(locomotion_source.relative_to(config.groot_root))},
            "snapshot": {
                "coordinate_system": {"up_axis": "Z", "unit": "meter"},
                "bounds": {"minimum_m": [-10, -10, -0.1], "maximum_m": [10, 10, 4]},
                "spawn_points": [{"id": "default", "position_m": [0, 0, 0.8]}],
                "query_capabilities": ["get_scene_summary", "list_objects"],
                "intervention_capabilities": ["set_robot_spawn"],
            },
        },
        "robots/unitree_g1_locomotion.json": {
            "id": "unitree_g1_locomotion",
            "revision": locomotion_revision,
            "status": "READY",
            "compatibility": {"profile_ids": ["29dof"]},
        },
        "controllers/groot_balance.json": {
            "id": "groot_balance",
            "revision": balance_revision,
            "status": "READY",
        },
        "controllers/groot_locomotion.json": {
            "id": "groot_locomotion",
            "revision": walk_revision,
            "status": "READY",
        },
        "policies/groot_balance_policy.json": {
            "id": "groot_balance_policy",
            "revision": balance_revision,
            "status": "READY",
        },
        "policies/groot_walk_policy.json": {
            "id": "groot_walk_policy",
            "revision": walk_revision,
            "status": "READY",
        },
        "tasks/locomotion.json": {
            "id": "locomotion",
            "revision": "schema:locomotion@1.0",
            "status": "READY",
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
    resources["tasks/navigation.json"] = {
        "id": "navigation",
        "revision": "schema:navigation@1.0",
        "status": "READY",
    }
    for relative, payload in resources.items():
        path = config.data_root / "registries" / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
