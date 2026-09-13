"""Terrain bundles stay isolated from legacy navigation registration/execution."""

import json
from types import SimpleNamespace

import pytest

from procedural_world.export import export_bundle
from procedural_world.terrain import generate_course
from procedural_world.terrain_presets import preset
from simulation_server.registry import ManifestRegistry
from simulation_server.worlds import register_world, resolve_world, validate_bundle


@pytest.mark.parametrize("name", ["flat", "ramp", "stairs", "low_friction"])
def test_terrain_registration_rejected_without_side_effects(tmp_path, name):
    spec = generate_course(preset(name))
    bundle = export_bundle(spec, tmp_path / "bundles")
    assert validate_bundle(bundle).revision == spec.revision
    data_root = tmp_path / "server"
    with pytest.raises(ValueError, match="legacy navigation server registration"):
        register_world(bundle, data_root)
    assert not data_root.exists()
    assert validate_bundle(bundle).revision == spec.revision


def test_preexisting_terrain_registration_cannot_resolve(tmp_path):
    spec = generate_course(preset("ramp"))
    bundle = export_bundle(spec, tmp_path / "bundles")
    registry = ManifestRegistry(tmp_path / "registries")
    folder = registry.root / "scenes"
    folder.mkdir()
    path = folder / f"{spec.scene_id}.json"
    manifest = {
        "id": spec.scene_id,
        "revision": f"sha256:{spec.revision}",
        "backend": {"kind": "procedural_world_v1", "bundle": str(bundle)},
    }
    path.write_text(json.dumps(manifest))
    before = path.read_bytes()
    ref = SimpleNamespace(id=spec.scene_id, revision=manifest["revision"])
    with pytest.raises(ValueError, match="legacy navigation server execution"):
        resolve_world(registry, ref)
    assert path.read_bytes() == before
    assert validate_bundle(bundle, ref.revision).revision == spec.revision
