"""CPU geometry/planning checks; no inference or claims of G1 success."""

from pathlib import Path

import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path.contracts import CorridorFixture, Fixture, ObstacleFixture
from clear_path.obstacles import static_obstacles
from clear_path.scene_space import axes_for_schema, scene_from_parameters
from robot_vlm.navigation_tools import (
    PLANNING_RADIUS,
    RADIUS,
    RESOLUTION,
    clearances,
    plan,
    rectangles,
    segment_clear,
)
from robot_vlm.policy import Geometry, Observation
from robot_vlm.scene_config import validate_scene


def observation(config):
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    obs = Observation(
        state_version=0,
        simulation_time_s=0.0,
        goal_xy_m=list(fixture.GOAL),
        base_xyz_m=[*fixture.SPAWN, 0.74],
        yaw_rad=0.0,
        previous_execution="none",
        camera_name="synthetic",
        camera_fovy_deg=65.0,
        camera_xyz_m=[1.0, 0.0, 1.0],
        camera_rotation_matrix=np.eye(3).ravel().tolist(),
        geometry=[
            Geometry(
                object_id=model.geom(i).name,
                center_m=data.geom_xpos[i].tolist(),
                size_m=(2 * model.geom_size[i]).tolist(),
                rotation_matrix=data.geom_xmat[i].tolist(),
            )
            for i in range(model.ngeom)
        ],
    )
    return obs, model, data


def assert_route_contracts(obs, nav, route):
    """Same geometry, distinct radii/endpoints; a preview is NOT the live route."""
    assert nav["effective_radius_m"] == pytest.approx(RADIUS)
    assert route["radius_m"] == RADIUS
    assert route["planning_radius_m"] == PLANNING_RADIUS > RADIUS
    points = nav["path_xy_m"]
    assert bool(points) == nav["reachable"]
    for x, y in points:
        row = int((y - nav["origin_xy_m"][1]) / nav["resolution_m"])
        col = int((x - nav["origin_xy_m"][0]) / nav["resolution_m"])
        assert nav["blocked"][row][col] == 0
    if points:
        assert np.linalg.norm(np.array(points[0]) - fixture.SPAWN) <= RESOLUTION / 2**0.5 + 1e-10
        assert np.linalg.norm(np.array(points[-1]) - fixture.GOAL) <= RESOLUTION / 2**0.5 + 1e-10
        assert all(
            sum(abs(x - y) for x, y in zip(a, b)) == pytest.approx(RESOLUTION)
            for a, b in zip(points, points[1:])
        )
    if route["status"] == "path_found":
        floor, rects = rectangles(obs)
        path = route["path_xy_m"]
        assert path[0] == obs.base_xyz_m[:2] and path[-1] == list(fixture.GOAL)
        assert all(segment_clear(a, b, floor, rects) for a, b in zip(path, path[1:]))
        assert all(
            min(clearances(p, floor, rects)) >= PLANNING_RADIUS + RESOLUTION / 2**0.5 - 1e-9
            for p in path[1:-1]
        )
    else:
        assert route["status"] in {"no_path", "blocked_endpoint", "no_tracking_clearance"}
        assert route["path_xy_m"] == []


@pytest.mark.parametrize(
    "width,offset,reachable",
    [
        (4.0, 0.0, True),
        (1.6, 0.0, False),
        (2.4, 0.0, False),
        (2.4, 1.0, True),
        (2.4, -1.0, True),
    ],
)
def test_generated_map_and_robot_planner_use_their_declared_contracts(width, offset, reachable):
    config = CorridorFixture(corridor_width_m=width, box_lateral_fraction=offset)
    obs, model, data = observation(config)
    nav = fixture.navigation_map(config)
    assert nav["scene_revision"] == fixture.identity(config)
    assert nav["reachable"] is reachable
    route = plan(obs, list(fixture.GOAL))
    assert (route["status"] == "path_found") is reachable
    assert_route_contracts(obs, nav, route)
    graph = fixture.graph(config)
    assert graph["meta"]["scene_revision"] == fixture.identity(config)
    assert not any(obj["id"] == "push_goal" for obj in graph["objects"])
    for obj in graph["objects"]:
        if obj["id"] == "robot_goal":
            assert obj["position"][:2] == list(fixture.GOAL)
            continue
        name = "clear_box_geom" if obj["id"] == "clear_box" else obj["id"]
        g = model.geom(name).id
        assert obj["position"] == pytest.approx(data.geom_xpos[g])
        assert obj["size"] == pytest.approx(2 * model.geom_size[g])
    assert data.body("clear_box").xpos[:2] == pytest.approx(fixture.box_start(config))
    assert model.body("clear_box").mass == pytest.approx(config.box_mass_kg)
    assert model.geom("clear_floor").friction[0] == pytest.approx(config.floor_friction)


@pytest.mark.parametrize("width", [1.6, 2.4, 4.0])
@pytest.mark.parametrize("offset", [-1.0, 0.0, 1.0])
def test_full_parameter_corners_no_initial_box_wall_interpenetration(width, offset):
    config = CorridorFixture(corridor_width_m=width, box_lateral_fraction=offset)
    _, model, data = observation(config)
    gap = width / 2 - abs(fixture.box_start(config)[1]) - fixture.BOX_SIZE[1] / 2
    assert gap >= 0.05 - 1e-12
    box, floor = model.geom("clear_box_geom").id, model.geom("clear_floor").id
    assert all(
        box not in (c.geom1, c.geom2) or floor in (c.geom1, c.geom2)
        for c in data.contact
        if c.dist < 0
    )


@pytest.mark.parametrize(
    "extra",
    [
        {"corridor_width_m": 1.59},
        {"corridor_width_m": 4.01},
        {"box_lateral_fraction": 1.01},
        {"corridor_width_m": float("nan")},
        {"footprint_radius_m": 0.4},
        {"clearance_m": 0.1},
        {"goal_xy_m": [2.0, 0.0]},
        {"box_size": [0.1, 0.1, 0.1]},
    ],
)
def test_scene_mutation_cannot_change_robot_task_or_leave_domain(extra):
    with pytest.raises(ValueError):
        validate_scene({"schema_version": "clear-path-corridor-v2", **extra})


def test_versions_and_exact_candidate_axes_are_not_interchangeable():
    with pytest.raises(ValueError):
        validate_scene({"corridor_width_m": 4.0})
    with pytest.raises(ValueError):
        axes_for_schema("unknown")
    with pytest.raises(ValueError):
        scene_from_parameters({"box_mass_kg": 2.0})
    assert isinstance(validate_scene(), Fixture)
    assert not isinstance(validate_scene(), CorridorFixture)
    assert fixture.identity(Fixture()) != fixture.identity(CorridorFixture())


@pytest.mark.parametrize("config", [CorridorFixture(), ObstacleFixture(obstacle_1_yaw_deg=45.0)])
def test_real_g1_composition_preserves_actuators_and_gait_observation(config):
    from clear_path.audit import inspect

    source = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/"
        "sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not source.is_file():
        pytest.skip("external G1 assets unavailable")
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config, source))
    audit = inspect(source, model)
    assert audit["robot_joint_identity_preserved"] and audit["gait_observation_equal"]
    assert audit["robot_actuators"] == 29
    assert not audit["gpu_policy_executed"]


def test_offline_preview_cli_outputs_static_report_not_rollout(tmp_path):
    import json
    import os
    import subprocess
    import sys

    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project / "tools/preview_corridor_scenes.py"),
            "--output-root",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        timeout=45,
        env={**os.environ, "OPENAI_API_KEY": "synthetic-must-not-be-used"},
    )
    assert result.returncode == 0, result.stderr
    root = next(tmp_path.iterdir())
    summary = json.loads((root / "summary.json").read_text())
    assert summary["api_calls"] == summary["robot_rollouts"] == summary["physics_steps"] == 0
    assert [r["static_path_exists"] for r in summary["scenes"]] == [True, False, True]
    assert {r["task_outcome"] for r in summary["scenes"]} == {"NOT_EXECUTED"}
    for row in summary["scenes"]:
        folder = root / row["directory"]
        assert (folder / "map.png").is_file()
        nav = json.loads((folder / "navigation_map.json").read_text())
        assert nav["scene_revision"] == row["scene_revision"]
    assert not list(root.rglob("*.gif")) and not list(root.rglob("*.mp4"))
    assert "synthetic-must-not-be-used" not in (root / "report.html").read_text()


@pytest.mark.parametrize("seed", range(24))
def test_obstacles_map_graph_and_oriented_physics_agree(seed):
    from failure_client.methods.behavior_feedback import uniform_scene

    schema = "clear-path-obstacles-v3"
    config = scene_from_parameters(uniform_scene(seed, "test", schema=schema), schema)
    obs, model, data = observation(config)
    nav, graph = fixture.navigation_map(config), fixture.graph(config)
    route = plan(obs, list(fixture.GOAL))
    assert_route_contracts(obs, nav, route)
    assert nav["schema_version"] == "clear-path-map-v3"
    assert graph["meta"]["scene_revision"] == nav["scene_revision"] == fixture.identity(config)
    assert set(fixture.world_geom_names(config)) == {model.geom(i).name for i in range(model.ngeom)}
    nodes = {o["id"]: o for o in graph["objects"]}
    for row in static_obstacles(config):
        node = nodes[row["id"]]
        g = model.geom(row["id"]).id
        assert node["position"] == pytest.approx(data.geom_xpos[g])
        assert node["extra"]["local_size_m"] == pytest.approx(2 * model.geom_size[g])
        assert node["extra"]["rotation_matrix"] == pytest.approx(data.geom_xmat[g])
        aabb = np.abs(data.geom_xmat[g].reshape(3, 3)) @ (2 * model.geom_size[g])
        assert node["size"] == pytest.approx(aabb)
        assert node["movable"] is False and node["extra"]["dynamic"] is False
        assert node["extra"]["mujoco_geom_name"] == row["id"]
        assert node["extra"]["contact_annotation"] == "diagnostic_only"
    # One dynamic body only; adding static blocks must not grow the free-joint state.
    assert model.nq == 7 and model.nv == 6


def test_static_preview_path_is_not_a_live_tracking_feasibility_promise():
    from failure_client.methods.behavior_feedback import uniform_scene

    schema = "clear-path-obstacles-v3"
    config = scene_from_parameters(uniform_scene(1, "test", schema=schema), schema)
    obs, _, _ = observation(config)
    nav = fixture.navigation_map(config)
    route = plan(obs, list(fixture.GOAL))
    assert nav["reachable"] is True and route["status"] == "no_path"
    assert_route_contracts(obs, nav, route)


@pytest.mark.parametrize("width", [1.6, 4.0])
@pytest.mark.parametrize("yaw", [-90.0, -45.0, 0.0, 45.0, 90.0])
@pytest.mark.parametrize("fraction", [-1.0, 0.0, 1.0])
def test_obstacle_extreme_sizes_keep_initial_geometry_nonpenetrating(width, yaw, fraction):
    config = ObstacleFixture(
        corridor_width_m=width,
        box_lateral_fraction=fraction,
        obstacle_1_x_m=2.75,
        obstacle_2_x_m=5.25,
        **{
            f"obstacle_{i}_{axis}": value
            for i in (1, 2)
            for axis, value in {
                "size_x_m": 0.8,
                "size_y_m": 0.8,
                "yaw_deg": yaw,
                "lateral_fraction": fraction,
            }.items()
        },
    )
    _, model, data = observation(config)
    for row in static_obstacles(config):
        x0, x1, y0, y1 = row["aabb_xy_m"]
        assert y0 >= -width / 2 + 0.05 - 1e-12
        assert y1 <= width / 2 - 0.05 + 1e-12
        assert x0 > fixture.SPAWN[0] + 0.4 and x1 < fixture.GOAL[0] - 0.4
        assert x1 < 3.6 or x0 > 4.4
    floor = model.geom("clear_floor").id
    assert all(floor in (c.geom1, c.geom2) for c in data.contact if c.dist < -1e-10)


def test_obstacle_contract_bounds_fixed_count_and_height_projection():
    schema = "clear-path-obstacles-v3"
    axes = axes_for_schema(schema)
    assert len(axes) == 17
    for axis, (lo, hi) in axes.items():
        field = ObstacleFixture.model_fields[axis]
        assert any(getattr(m, "ge", None) == lo for m in field.metadata)
        assert any(getattr(m, "le", None) == hi for m in field.metadata)
        for value in (lo - 0.01, hi + 0.01, float("inf"), float("nan")):
            with pytest.raises(ValueError):
                validate_scene({"schema_version": schema, axis: value})
    for extra in ({"obstacle_count": 3}, {"goal_xy_m": [2.0, 0.0]}, {"clearance_m": 0.1}):
        with pytest.raises(ValueError):
            validate_scene({"schema_version": schema, **extra})
    low, high = ObstacleFixture(obstacle_1_height_m=0.1), ObstacleFixture(obstacle_1_height_m=1.2)
    assert fixture.navigation_map(low)["blocked"] == fixture.navigation_map(high)["blocked"]
    assert fixture.identity(low) != fixture.identity(high)


def test_obstacle_offline_preview_cli(tmp_path):
    import json
    import subprocess
    import sys

    project = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(project / "tools/preview_corridor_scenes.py"),
            "--preset",
            "obstacles",
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
    assert summary["api_calls"] == summary["robot_rollouts"] == summary["physics_steps"] == 0
    assert len(summary["scenes"]) == 4
    assert summary["scenes"][-1]["static_path_exists"] is False
    assert summary["scenes"][0]["static_path_exists"] is True
    for row in summary["scenes"]:
        assert row["task_outcome"] == "NOT_EXECUTED"
        assert (root / row["directory"] / "map.png").is_file()
    assert not list(root.rglob("*.gif")) and not list(root.rglob("*.mp4"))
