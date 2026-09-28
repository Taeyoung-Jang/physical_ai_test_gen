"""CPU geometry/planning checks; no inference or claims of G1 success."""

from pathlib import Path

import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path.contracts import CorridorFixture, Fixture
from clear_path.scene_space import axes_for_schema, scene_from_parameters
from robot_vlm.navigation_tools import plan
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
def test_generated_map_matches_robot_local_planner(width, offset, reachable):
    config = CorridorFixture(corridor_width_m=width, box_lateral_fraction=offset)
    obs, model, data = observation(config)
    nav = fixture.navigation_map(config)
    assert nav["scene_revision"] == fixture.identity(config)
    assert nav["reachable"] is reachable
    route = plan(obs, list(fixture.GOAL))
    assert (route["status"] == "path_found") is reachable
    if reachable:
        assert np.asarray(nav["path_xy_m"]) == pytest.approx(np.asarray(route["path_xy_m"]))
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


def test_real_g1_composition_preserves_actuators_and_gait_observation():
    from clear_path.audit import inspect

    source = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/"
        "sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not source.is_file():
        pytest.skip("external G1 assets unavailable")
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(CorridorFixture(), source))
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
