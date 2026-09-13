import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import replace

import numpy as np
import pytest

from procedural_world import Config, generate, navigation_map, scene_graph
from procedural_world.core import Box
from procedural_world.export import export_bundle, mujoco_xml
from scene_graph import SceneGraph


@pytest.mark.parametrize("mode", ["rooms", "maze"])
@pytest.mark.parametrize("seed", [0, 1, 7])
def test_seeded_connected_world(mode, seed):
    config = Config(mode=mode, seed=seed, obstacle_count=2)
    spec = generate(config)
    assert spec == generate(config)
    assert len([b for b in spec.boxes if b.mutable]) == 2
    nav = navigation_map(spec)
    assert nav["reachable"] and nav["all_region_centers_reachable"]
    for (x, y), (nx, ny) in zip(nav["path_cells"], nav["path_cells"][1:]):
        assert abs(nx - x) + abs(ny - y) == 1
        assert nav["blocked"][y][x] == 0
    # Independently sample the entire world path against the original metric boxes.
    radius = config.robot_radius_m + config.safety_margin_m
    for a, b in zip(nav["path_xy_m"], nav["path_xy_m"][1:]):
        for t in np.linspace(0, 1, 5):
            p = np.array(a) * (1 - t) + np.array(b) * t
            for box in spec.boxes:
                delta = np.maximum(np.abs(p - box.position[:2]) - np.array(box.size[:2]) / 2, 0)
                assert np.linalg.norm(delta) > radius - 1e-8


def test_seed_changes_world():
    assert generate(Config(seed=0)).revision != generate(Config(seed=1)).revision


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "other"},
        {"width": 10},
        {"height": 3},
        {"obstacle_count": -1},
        {"cell_size_m": float("nan")},
        {"robot_radius_m": 1},
        {"subdivisions": 100},
        {"seed": 1.5},
        {"wall_height_m": 0},
    ],
)
def test_invalid_config(kwargs):
    with pytest.raises(ValueError):
        generate(Config(**kwargs))


def test_impossible_room_request_is_not_silently_reduced():
    with pytest.raises(ValueError, match="cannot fit"):
        generate(Config(width=9, height=9, room_count=30))


def test_graph_and_xml_share_metric_geometry():
    spec = generate(Config(seed=7, width=17))
    graph = scene_graph(spec)
    assert SceneGraph.from_json(graph.to_json()).to_dict() == graph.to_dict()
    root = ET.fromstring(mujoco_xml(spec))
    geoms = {g.attrib["name"]: g for g in root.findall("worldbody/geom")}
    for box in spec.boxes:
        node = graph.get_object(box.id)
        assert node.position == list(box.position)
        assert node.size == list(box.size)
        assert np.allclose(np.fromstring(geoms[box.id].attrib["pos"], sep=" "), node.position)
        assert np.allclose(np.fromstring(geoms[box.id].attrib["size"], sep=" ") * 2, node.size)
    ids = {o.id for o in graph.objects} | {s.id for s in graph.support_surfaces}
    assert len({o.id for o in graph.objects}) == len(graph.objects)
    assert all(r.source in ids and r.target in ids for r in graph.relations)


def test_blocked_spawn_and_large_footprint_fail():
    spec = generate(Config(obstacle_count=0))
    box = Box("block_spawn", "obstacle", (*spec.spawn_xy, 0.5), (1, 1, 1))
    assert not navigation_map(replace(spec, boxes=spec.boxes + (box,)))["reachable"]
    assert not navigation_map(replace(spec, config=replace(spec.config, robot_radius_m=100)))[
        "reachable"
    ]


def test_export_checksums_and_no_overwrite(tmp_path):
    spec = generate(Config())
    target = export_bundle(spec, tmp_path)
    manifest = json.loads((target / "manifest.json").read_text())
    for name, record in manifest["artifacts"].items():
        assert hashlib.sha256((target / name).read_bytes()).hexdigest() == record["sha256"]
    assert (target / "preview.png").stat().st_size > 1000
    with pytest.raises(FileExistsError):
        export_bundle(spec, tmp_path)


def test_mujoco_compiles_and_matches_graph():
    mujoco = pytest.importorskip("mujoco")
    spec = generate(Config(mode="maze", obstacle_count=2))
    model = mujoco.MjModel.from_xml_string(mujoco_xml(spec))
    assert model.ngeom == len(spec.boxes) + 1
    assert model.nq == 0  # This is a static world, not a G1 navigation run.
    for box in spec.boxes:
        geom = model.geom(box.id)
        assert np.allclose(geom.pos, box.position)
        assert np.allclose(geom.size * 2, box.size)
    assert math.isfinite(model.stat.extent)
