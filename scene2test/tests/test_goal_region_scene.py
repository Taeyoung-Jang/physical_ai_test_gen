"""Initial geometry and CPU composition, never a claim of robot manipulation success."""

import json
import math
import random
import subprocess
import sys
import xml.etree.ElementTree as ET
from itertools import product
from pathlib import Path

import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path.contracts import GoalRegionFixture, ObstacleFixture
from clear_path.obstacles import static_obstacles
from clear_path.scene_space import axes_for_schema, scene_from_parameters
from robot_vlm.scene_config import validate_scene
from robot_vlm.task_outcome import task_contract

PROJECT = Path(__file__).resolve().parents[1]
SCHEMA = "clear-path-goal-region-v4"


@pytest.mark.parametrize(
    "name,relation,reachable",
    [
        ("clear", "CLEAR", True),
        ("partial", "PARTIAL", False),
        ("covered", "FULLY_COVERED", False),
    ],
)
def test_presets_share_goal_and_geometry_across_outputs(name, relation, reachable):
    config = validate_scene(
        json.loads((PROJECT / f"config/scenes/goal_region_{name}.json").read_text())
    )
    assert isinstance(config, GoalRegionFixture)
    contract = task_contract(fixture.GOAL, 10, None)
    projection = fixture.initial_goal_relation(config, radius_m=contract["goal"]["radius_m"])
    assert projection["relation"] == relation and projection["goal_outcome"] is None
    assert projection["object_movable"] is True
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert model.nq == 7 and model.nv == 6  # same single free object, no robot
    graph = fixture.graph(config)
    nav = fixture.navigation_map(config)
    assert nav["schema_version"] == "clear-path-map-v4"
    assert graph["meta"]["scene_revision"] == nav["scene_revision"] == fixture.identity(config)
    assert graph["meta"]["initial_goal_relation"] == projection
    assert nav["reachable"] is reachable  # NOT a goal verdict
    assert not any(o["id"] == "push_goal" for o in graph["objects"])
    for obj in graph["objects"]:
        if obj["id"] == "robot_goal":
            assert obj["position"][:2] == list(fixture.GOAL)
            continue
        g = model.geom("clear_box_geom" if obj["id"] == "clear_box" else obj["id"]).id
        assert obj["position"] == pytest.approx(data.geom_xpos[g])
        aabb_size = np.abs(data.geom_xmat[g].reshape(3, 3)) @ (2 * model.geom_size[g])
        assert obj["size"] == pytest.approx(aabb_size)
    assert set(fixture.world_geom_names(config)) == {model.geom(i).name for i in range(model.ngeom)}


def test_all_domain_samples_clear_box_from_walls_and_static_blocks():
    axes = axes_for_schema(SCHEMA)
    assert len(axes) == 18
    rng = random.Random(17)
    samples = [{k: rng.uniform(*v) for k, v in axes.items()} for _ in range(200)]
    for x, width, side, yaw in product((6.8, 7.5), (1.6, 4.0), (-1.0, 0.0, 1.0), (-45.0, 45.0)):
        p = {k: v[1] for k, v in axes.items()}
        p.update(
            box_goal_x_m=x,
            corridor_width_m=width,
            box_lateral_fraction=side,
            obstacle_2_yaw_deg=yaw,
        )
        samples.append(p)
    for p in samples:
        config = scene_from_parameters(p, SCHEMA)
        x, y = fixture.box_start(config)
        box = (x - 0.4, x + 0.4, y - 0.55, y + 0.55)
        for a, b, c, d in [
            *fixture.walls(config).values(),
            *(o["aabb_xy_m"] for o in static_obstacles(config)),
        ]:
            assert box[1] <= a or box[0] >= b or box[3] <= c or box[2] >= d
        assert x - 0.4 - (5.75 + math.hypot(0.8, 0.8) / 2) > 0.08
        assert 8 - (x + 0.4) >= 0.1 - 1e-12


@pytest.mark.parametrize(
    "extra",
    [
        {"box_goal_x_m": 6.79},
        {"box_goal_x_m": 7.51},
        {"box_goal_x_m": float("nan")},
        {"goal_xy_m": [5.0, 0.0]},
        {"footprint_radius_m": 0.4},
        {"clearance_m": 0.1},
    ],
)
def test_v4_never_accepts_task_or_robot_mutation(extra):
    with pytest.raises(ValueError):
        validate_scene({"schema_version": SCHEMA, **extra})


def test_v3_keeps_central_box_and_cannot_accept_v4_axis():
    config = ObstacleFixture()
    assert fixture.box_start(config) == (4.0, 0.0)
    assert fixture.navigation_map(config)["schema_version"] == "clear-path-map-v3"
    assert "initial_goal_relation" not in fixture.graph(config)["meta"]
    with pytest.raises(ValueError):
        validate_scene({"schema_version": config.schema_version, "box_goal_x_m": 7.0})
    assert fixture.identity(config) != fixture.identity(GoalRegionFixture())


def test_real_g1_assets_preserve_joint_order_without_policy_execution():
    from clear_path.audit import inspect

    source = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/"
        "sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not source.is_file():
        pytest.skip("external G1 assets unavailable")
    config = GoalRegionFixture()
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config, source))
    result = inspect(source, model)
    assert result["robot_joint_identity_preserved"] and result["gait_observation_equal"]
    assert result["robot_actuators"] == 29 and not result["gpu_policy_executed"]
    root = ET.fromstring(fixture.world_xml(config, source))
    assert root.find("worldbody/body[@name='clear_box']/freejoint") is not None


def test_preview_outputs_three_scenes_and_png_not_rollouts(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT / "tools/preview_corridor_scenes.py"),
            "--preset",
            "goal_region",
            "--output-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    root = next(tmp_path.iterdir())
    summary = json.loads((root / "summary.json").read_text())
    assert summary["robot_rollouts"] == summary["api_calls"] == summary["physics_steps"] == 0
    assert [r["initial_goal_relation"]["relation"] for r in summary["scenes"]] == [
        "CLEAR",
        "PARTIAL",
        "FULLY_COVERED",
    ]
    assert all(r["task_outcome"] == "NOT_EXECUTED" for r in summary["scenes"])
    assert len(list(root.rglob("map.png"))) == 3
    assert not list(root.rglob("*.gif"))
