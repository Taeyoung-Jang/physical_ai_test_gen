"""CPU scene/provenance tests, not human-risk discovery or robot performance."""

import itertools
import random
from pathlib import Path

import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path.audit import inspect
from clear_path.contracts import GoalRegionFixture, HumanFixture
from clear_path.humans import human_geometry, human_scene
from clear_path.obstacles import static_obstacles
from clear_path.scene_space import axes_for_schema, scene_from_parameters
from robot_vlm.scene_config import validate_scene

SCHEMA = "clear-path-human-v5"


def test_human_geometry_map_graph_and_physics_agree():
    config = HumanFixture()
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert (model.nq, model.nv) == (7, 6)
    assert set(fixture.world_geom_names(config)) == {model.geom(i).name for i in range(model.ngeom)}
    graph, nav = fixture.graph(config), fixture.navigation_map(config)
    human = human_geometry(config)[0]
    node = next(o for o in graph["objects"] if o["id"] == human["id"])
    g = model.geom(human["id"]).id
    assert node["role"] == "human_zone"
    assert node["extra"]["semantic_role"] == "simulated_human_proxy"
    assert node["extra"]["mujoco_geom_name"] == human["id"]
    assert node["position"] == pytest.approx(data.geom_xpos[g])
    assert node["size"] == pytest.approx(2 * model.geom_size[g])
    assert graph["meta"]["human_proximity"] == human_scene(config)
    assert nav["schema_version"] == "clear-path-map-v5"
    assert graph["meta"]["scene_revision"] == nav["scene_revision"] == fixture.identity(config)
    x, y = human["center_m"][:2]
    ix = int((x - nav["origin_xy_m"][0]) / nav["resolution_m"])
    iy = int((y - nav["origin_xy_m"][1]) / nav["resolution_m"])
    assert nav["blocked"][iy][ix] == 1


def test_full_human_domain_has_no_initial_object_overlap():
    rng = random.Random(17)
    axes = axes_for_schema(SCHEMA)
    assert len(axes) == 20
    samples = [{k: rng.uniform(*v) for k, v in axes.items()} for _ in range(100)]
    for width, x, side, yaw in itertools.product(
        (1.6, 4.0), (3.65, 4.35), (-1.0, 1.0), (-45.0, 45.0)
    ):
        p = {k: v[1] for k, v in axes.items()}
        p.update(
            corridor_width_m=width,
            human_x_m=x,
            human_lateral_fraction=side,
            obstacle_1_yaw_deg=yaw,
            obstacle_2_yaw_deg=yaw,
        )
        samples.append(p)
    for p in samples:
        config = scene_from_parameters(p, SCHEMA)
        boxes = [o["aabb_xy_m"] for o in static_obstacles(config)]
        x, y = fixture.box_start(config)
        boxes.append([x - 0.4, x + 0.4, y - 0.55, y + 0.55])
        for a, b in itertools.combinations(boxes, 2):
            assert a[1] <= b[0] or a[0] >= b[1] or a[3] <= b[2] or a[2] >= b[3]
        for a, b, c, d in boxes:
            assert 0 <= a < b <= 8
            assert -config.corridor_width_m / 2 <= c < d <= config.corridor_width_m / 2


@pytest.mark.parametrize(
    "extra",
    [
        {"human_x_m": 3.64},
        {"human_lateral_fraction": 1.01},
        {"human_x_m": float("nan")},
        {"protected_radius_m": 3.0},
        {"min_continuous_exposure_s": 0.01},
        {"human_size_m": [1, 1, 1]},
        {"footprint_radius_m": 0.4},
        {"goal_xy_m": [5.0, 0.0]},
    ],
)
def test_scene_cannot_mutate_measurement_task_or_robot_contract(extra):
    with pytest.raises(ValueError):
        validate_scene({"schema_version": SCHEMA, **extra})


def test_v4_has_no_human_metadata_or_geometry():
    config = GoalRegionFixture()
    assert human_geometry(config) == []
    assert "human_proximity" not in fixture.graph(config)["meta"]
    assert fixture.navigation_map(config)["schema_version"] == "clear-path-map-v4"
    with pytest.raises(ValueError):
        validate_scene({"schema_version": config.schema_version, "human_x_m": 4.0})


def test_human_preserves_actual_g1_joints_and_gait_observation():
    source = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not source.is_file():
        pytest.skip("external G1 assets unavailable")
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(HumanFixture(), source))
    result = inspect(source, model)
    assert result["robot_joint_identity_preserved"] and result["gait_observation_equal"]
    assert model.nu == 29
    assert np.isfinite(mujoco.MjData(model).qpos).all()
