"""Trusted local scene ingestion and revision-checked G1 model composition."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from procedural_world.core import Box, Config, Region, SceneSpec, navigation_map, scene_graph

from .registry import ManifestRegistry


def load_spec(path: Path) -> SceneSpec:
    d = json.loads(path.read_text())
    cfg = Config(**d["config"])
    cfg.validate()
    spec = SceneSpec(
        cfg,
        tuple(Box(**b) for b in d["boxes"]),
        tuple(Region(**r) for r in d["regions"]),
        tuple(tuple(c) for c in d["connections"]),
        tuple(d["spawn_xy"]),
        tuple(d["goal_xy"]),
        d["generator_version"],
    )
    ids = set()
    for b in spec.boxes:
        if not re.fullmatch(r"[A-Za-z0-9_]+", b.id) or b.id in ids:
            raise ValueError("invalid or duplicate geometry ID")
        ids.add(b.id)
        if len(b.position) != 3 or len(b.size) != 3:
            raise ValueError("geometry must be 3D")
        if not all(math.isfinite(v) for v in [*b.position, *b.size]) or min(b.size) <= 0:
            raise ValueError("invalid geometry size/position")
        if abs(b.position[2] - b.size[2] / 2) > 1e-8:
            raise ValueError("v1 navigation supports floor-supported static boxes only")
    for xy in (spec.spawn_xy, spec.goal_xy):
        if len(xy) != 2 or not all(math.isfinite(v) for v in xy):
            raise ValueError("invalid navigation endpoint")
    return spec


def validate_bundle(bundle: Path, expected_revision: str | None = None) -> SceneSpec:
    manifest = json.loads((bundle / "manifest.json").read_text())
    required = {"scene_spec.json", "scene_graph.json", "navigation_map.json", "scene.xml"}
    if not required <= manifest["artifacts"].keys():
        raise ValueError("incomplete world bundle")
    for name, record in manifest["artifacts"].items():
        if Path(name).name != name:
            raise ValueError("invalid artifact name")
        data = (bundle / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != record["sha256"] or len(data) != record["bytes"]:
            raise ValueError(f"world artifact checksum mismatch: {name}")
    spec = load_spec(bundle / "scene_spec.json")
    if spec.revision != manifest["scene_revision"] or spec.scene_id != manifest["scene_id"]:
        raise ValueError("world revision mismatch")
    if expected_revision and expected_revision != f"sha256:{spec.revision}":
        raise ValueError("requested scene revision differs from actual geometry")
    nav = navigation_map(spec)
    if not nav["reachable"] or not nav["all_region_centers_reachable"]:
        raise ValueError("scene has no valid navigation path")
    if json.loads((bundle / "navigation_map.json").read_text()) != nav:
        raise ValueError("navigation map differs from scene geometry")
    if json.loads((bundle / "scene_graph.json").read_text()) != scene_graph(spec).to_dict():
        raise ValueError("SceneGraph differs from scene geometry")
    return spec


def register_world(bundle: Path, data_root: Path) -> dict:
    spec = validate_bundle(bundle)
    destination = data_root / "assets" / "worlds" / spec.scene_id
    if not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, destination)
    validate_bundle(destination, f"sha256:{spec.revision}")
    cfg = spec.config
    manifest = {
        "id": spec.scene_id,
        "revision": f"sha256:{spec.revision}",
        "status": "READY",
        "backend": {"kind": "procedural_world_v1", "bundle": str(destination.resolve())},
        "compatibility": {"robot_ids": ["unitree_g1_locomotion"], "tasks": ["navigation@1.0"]},
        "snapshot": {
            "coordinate_system": {"up_axis": "Z", "unit": "meter"},
            "bounds": {
                "minimum_m": [0, 0, 0],
                "maximum_m": [
                    cfg.width * cfg.cell_size_m,
                    cfg.height * cfg.cell_size_m,
                    cfg.wall_height_m,
                ],
            },
            "objects": [
                {
                    "id": b.id,
                    "category": b.category,
                    "pose": {"position_m": list(b.position)},
                    "aabb": {
                        "minimum_m": [p - s / 2 for p, s in zip(b.position, b.size)],
                        "maximum_m": [p + s / 2 for p, s in zip(b.position, b.size)],
                    },
                    "collision_geom": f"world_{b.id}",
                }
                for b in spec.boxes
            ],
            "regions": [{"id": r.id, "center_xy_m": list(r.center)} for r in spec.regions]
            + [{"id": "goal", "center_xy_m": list(spec.goal_xy)}],
            "spawn_points": [{"id": "default", "position_m": [*spec.spawn_xy, 0.793]}],
            "query_capabilities": [
                "get_scene_summary",
                "list_objects",
                "get_object_pose",
                "get_aabb",
            ],
        },
    }
    folder = data_root / "registries" / "scenes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{spec.scene_id}.json"
    if path.exists():
        if json.loads(path.read_text()) != manifest:
            raise ValueError("refusing registry overwrite")
    else:
        with path.open("x") as f:
            json.dump(manifest, f, indent=2)
    return manifest


def resolve_world(registry: ManifestRegistry, scene) -> SceneSpec:
    manifest = registry.resolve("scenes", scene.id, scene.revision)
    if manifest.get("backend", {}).get("kind") != "procedural_world_v1":
        raise ValueError("navigation requires a registered procedural world")
    return validate_bundle(Path(manifest["backend"]["bundle"]), scene.revision)


def compose_model(spec: SceneSpec, groot_root: Path, output: Path):
    import mujoco

    source = groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    baseline = mujoco.MjModel.from_xml_path(str(source))
    root = ET.parse(source).getroot()
    compiler = root.find("compiler")
    meshdir = source.parent / compiler.get("meshdir", "")
    compiler.set("meshdir", str(meshdir.resolve()))
    bodies = root.findall("worldbody")
    for body in bodies:
        for child in list(body):
            if child.tag == "geom":
                body.remove(child)  # Replace original ground; leave robot tree untouched.
    wb = bodies[0]
    cfg = spec.config
    sx, sy = cfg.width * cfg.cell_size_m, cfg.height * cfg.cell_size_m
    ET.SubElement(
        wb,
        "geom",
        name="world_floor",
        type="box",
        pos=f"{sx / 2} {sy / 2} -.1",
        size=f"{sx / 2} {sy / 2} .1",
        rgba=".7 .75 .8 1",
        friction=".8 .005 .0001",
    )
    for b in spec.boxes:
        ET.SubElement(
            wb,
            "geom",
            name=f"world_{b.id}",
            type="box",
            pos=" ".join(map(str, b.position)),
            size=" ".join(str(s / 2) for s in b.size),
            rgba=".95 .45 .15 1" if b.mutable else ".32 .39 .48 1",
            friction=".8 .005 .0001",
        )
    for name, xy, rgba in (
        ("spawn", spec.spawn_xy, ".1 .8 .4 1"),
        ("goal", spec.goal_xy, ".9 .2 .3 1"),
    ):
        ET.SubElement(
            wb,
            "site",
            name=f"world_{name}",
            type="cylinder",
            pos=f"{xy[0]} {xy[1]} .015",
            size=".25 .01",
            rgba=rgba,
        )
    model_path = output / "composed_scene.xml"
    ET.indent(root)
    model_path.write_text(ET.tostring(root, encoding="unicode"))
    model = mujoco.MjModel.from_xml_path(str(model_path))
    for kind, count in (
        (mujoco.mjtObj.mjOBJ_JOINT, baseline.njnt),
        (mujoco.mjtObj.mjOBJ_ACTUATOR, baseline.nu),
    ):
        assert [mujoco.mj_id2name(model, kind, i) for i in range(count)] == [
            mujoco.mj_id2name(baseline, kind, i) for i in range(count)
        ]
    assert (model.nq, model.nv, model.nu) == (baseline.nq, baseline.nv, baseline.nu)
    for b in spec.boxes:
        geom = model.geom(f"world_{b.id}")
        if not np.allclose(geom.pos, b.position) or not np.allclose(geom.size * 2, b.size):
            raise ValueError("compiled geometry differs from SceneGraph")
    resource_paths = [
        source,
        source.with_suffix(".yaml"),
        source.parent / "policy/GR00T-WholeBodyControl-Walk.onnx",
    ]
    resource_paths += [meshdir / mesh.attrib["file"] for mesh in root.findall("asset/mesh")]
    provenance = {
        str(p.relative_to(groot_root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in resource_paths
    }
    return model, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument(
        "--data-root", type=Path, default=Path("/workspace/g1_failure/runtime/server")
    )
    args = parser.parse_args()
    print(json.dumps(register_world(args.bundle, args.data_root), indent=2))


if __name__ == "__main__":
    main()
