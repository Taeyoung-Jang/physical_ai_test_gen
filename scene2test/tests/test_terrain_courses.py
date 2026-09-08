import json
from dataclasses import replace

import numpy as np
import pytest

from procedural_world.core import navigation_map, scene_graph
from procedural_world.export import export_bundle, mujoco_xml
from procedural_world.navigation_stages import stage_world
from procedural_world.terrain import generate_course, ground_height, segment_traversable
from procedural_world.terrain_presets import PRESETS, apply_parameters, preset
from simulation_server.worlds import validate_bundle


@pytest.mark.parametrize("name", PRESETS)
def test_presets_have_consistent_geometry_and_planned_path(name):
    spec = generate_course(preset(name))
    nav = navigation_map(spec)
    graph = scene_graph(spec)
    assert nav["reachable"]
    assert nav["scene_revision"] == spec.revision == graph.meta["scene_revision"]
    assert len(nav["height_m"]) == nav["height"]
    assert all(graph.get_object(s.id).role == "traversable_surface" for s in spec.surfaces)
    assert generate_course(preset(name)).revision == spec.revision


def test_legacy_revision_unchanged():
    assert (
        stage_world("obstacle").revision
        == "165669c66fefe87f315cdbfd2a5622a98ba4838bbd03e8002f221bc5ec46347f"
    )


def test_ramp_mesh_rays_equal_analytic_height():
    mujoco = pytest.importorskip("mujoco")
    spec = generate_course(preset("ramp"))
    model = mujoco.MjModel.from_xml_string(mujoco_xml(spec))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    for s in spec.surfaces:
        x, y = (s.x0 + s.x1) / 2, (s.y0 + s.y1) / 2
        geom = np.array([-1], dtype=np.int32)
        distance = mujoco.mj_ray(
            model,
            data,
            np.array([x, y, 5.0]),
            np.array([0.0, 0.0, -1.0]),
            np.array([0, 0, 1, 0, 0, 0], dtype=np.uint8),
            1,
            -1,
            geom,
        )
        assert 5 - distance == pytest.approx(s.height(x, y), abs=1e-6)
        assert model.geom(geom[0]).name == s.id
        assert mujoco.MjvOption().geomgroup[model.geom(s.id).group] == 1
    assert model.geom("floor").contype == 0 and model.geom("floor").conaffinity == 0


def test_bundle_roundtrip_and_tampering(tmp_path):
    spec = generate_course(preset("stairs"))
    bundle = export_bundle(spec, tmp_path)
    assert validate_bundle(bundle).revision == spec.revision
    path = bundle / "navigation_map.json"
    d = json.loads(path.read_text())
    d["height_m"][0][0] += 0.1
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="checksum"):
        validate_bundle(bundle)


def test_limits_reject_cliff_and_steep_ramp_not_robot_failure():
    spec = generate_course({"segments": [{"kind": "stairs", "step_height_m": 0.3, "count": 2}]})
    assert not navigation_map(spec)["reachable"]
    assert not segment_traversable(spec, spec.spawn_xy, spec.goal_xy)
    ramp = generate_course({"segments": [{"kind": "ramp", "angle_deg": 30, "length_m": 2}]})
    assert not navigation_map(ramp)["reachable"]


@pytest.mark.parametrize(
    "section",
    [
        {"kind": "ramp", "angle_deg": float("nan")},
        {"kind": "stairs", "count": 2.5},
        {"kind": "rough", "amplitude_m": -1},
        {"kind": "friction", "friction": 0},
        {"kind": "flat", "widht_m": 2},
        {"kind": "unknown"},
    ],
)
def test_invalid_parameters_rejected(section):
    with pytest.raises(ValueError):
        generate_course({"segments": [section]})


def test_parameter_application_and_revision():
    base = preset("ramp")
    changed = apply_parameters(base, {"segments.0.angle_deg": 10})
    assert base["segments"][0]["angle_deg"] == 5
    assert generate_course(base).revision != generate_course(changed).revision
    spec = generate_course(base)
    assert replace(spec, floor_friction=0.4).revision != spec.revision
    assert ground_height(spec, (5, 8.1)) > 0


def test_surface_friction_controls_real_contact():
    mujoco = pytest.importorskip("mujoco")
    import xml.etree.ElementTree as ET

    spec = generate_course(preset("low_friction"))
    root = ET.fromstring(mujoco_xml(spec))
    surface = next(s for s in spec.surfaces if s.category == "friction")
    body = ET.SubElement(
        root.find("worldbody"),
        "body",
        name="test_ankle_roll",
        pos=f"{(surface.x0 + surface.x1) / 2} 8.1 .2",
    )
    ET.SubElement(body, "freejoint")
    ET.SubElement(body, "geom", type="box", size=".05 .05 .05", mass="1", friction="1 .005 .0001")
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding="unicode"))
    data = mujoco.MjData(model)
    for _ in range(250):
        mujoco.mj_step(model, data)
    contacts = [c for c in data.contact if c.dist <= 0]
    assert contacts
    assert all(c.friction[0] == pytest.approx(0.15) for c in contacts)
