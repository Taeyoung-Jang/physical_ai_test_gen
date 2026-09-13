
import numpy as np
import pytest
from fastapi.testclient import TestClient
from test_server_vertical_slice import GROOT_ROOT, _request

from failure_client.contracts import ResourceRef
from procedural_world.core import navigation_map
from procedural_world.export import export_bundle
from procedural_world.navigation_stages import stage_world
from simulation_server.config import ServerConfig
from simulation_server.main import create_app
from simulation_server.navigation import Follower, segment_free, simplify_path
from simulation_server.registry import ManifestRegistry
from simulation_server.worlds import compose_model, register_world, resolve_world, validate_bundle


@pytest.mark.parametrize("stage", ["straight", "corner", "obstacle", "rooms", "maze"])
def test_stage_path_and_simplification(stage):
    nav = navigation_map(stage_world(stage))
    path = simplify_path(nav)
    assert nav["reachable"]
    assert all(segment_free(a, b, nav) for a, b in zip(path, path[1:]))
    f = Follower(nav)
    assert np.isfinite(f.command(path[0], 0)).all()
    assert np.allclose(f.command(path[-1], 0), 0)


def test_world_registration_and_corruption(tmp_path):
    spec = stage_world("straight")
    bundle = export_bundle(spec, tmp_path / "generated")
    manifest = register_world(bundle, tmp_path / "server")
    registry = ManifestRegistry(tmp_path / "server/registries")
    ref = ResourceRef(id=spec.scene_id, revision=manifest["revision"])
    assert resolve_world(registry, ref).revision == spec.revision
    copied = tmp_path / "server/assets/worlds" / spec.scene_id
    (copied / "scene_graph.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        resolve_world(registry, ref)
    with pytest.raises(ValueError, match="revision"):
        validate_bundle(bundle, "sha256:wrong")


def test_composition_preserves_robot_and_maps_geometry(tmp_path):
    pytest.importorskip("mujoco")
    if not GROOT_ROOT.exists():
        pytest.skip("local GR00T assets required")
    model, hashes = compose_model(stage_world("obstacle"), GROOT_ROOT, tmp_path)
    assert model.nu == 29
    assert len(hashes) > 20
    assert np.allclose(model.geom("world_obstacle_0").size, [0.5, 0.5, 0.5])


def test_navigation_api_validation_and_probe(tmp_path):
    cfg = ServerConfig(
        data_root=tmp_path / "server", groot_root=GROOT_ROOT, execution_backend="probe"
    )
    with TestClient(create_app(cfg)) as client:
        spec = stage_world("straight")
        manifest = register_world(export_bundle(spec, tmp_path / "generated"), cfg.data_root)
        registry = client.get("/api/v1/registry/snapshot").json()
        request = _request(client).model_dump(mode="json", by_alias=True)
        for kind, ident in (
            ("robots", "unitree_g1_locomotion"),
            ("controllers", "groot_locomotion"),
            ("policies", "groot_walk_policy"),
        ):
            entry = next(e for e in registry[kind] if e["id"] == ident)
            key = {"robots": "robot", "controllers": "controller", "policies": "policy"}[kind]
            request["resources"][key] = {"id": ident, "revision": entry["revision"]}
        request["resources"]["robot"]["profile_id"] = "29dof"
        request["resources"]["scene"] = {"id": spec.scene_id, "revision": manifest["revision"]}
        request["task"] = {"schema": "navigation@1.0", "parameters": {"speed_mps": 0.3}}
        request["interventions"] = []
        response = client.post("/api/v1/rollouts", json=request, headers={"Idempotency-Key": "nav"})
        assert response.status_code == 202, response.text
        job = response.json()["job_id"]
        result = client.get(f"/api/v1/rollouts/{job}/result").json()
        assert not result["execution"]["valid"]  # Probe is never navigation success.
        request["task"]["parameters"]["speed_mps"] = 9
        assert (
            client.post(
                "/api/v1/rollouts", json=request, headers={"Idempotency-Key": "bad"}
            ).status_code
            == 422
        )
