"""P0/P1 geometry, contact dynamics and action contracts; no robot push claim."""

from pathlib import Path

import mujoco
import numpy as np
import pytest

from clear_path import audit, fixture
from clear_path.contracts import Action, Fixture, evaluate, validate_action


def test_fixture_paths_and_scenegraph():
    cfg = Fixture()
    initial = fixture.navigation_map(cfg)
    proposed = fixture.navigation_map(cfg, fixture.BOX_TARGET, hypothetical=True)
    assert not initial["reachable"] and proposed["reachable"]
    assert not initial["hypothetical"] and proposed["hypothetical"]
    assert fixture.navigation_map(cfg) == initial
    graph = fixture.graph(cfg)
    from scene_graph import SceneGraph

    restored = SceneGraph.from_dict(graph)
    assert restored.get_object("clear_box").movable
    assert restored.meta["frame"] == "world_m"
    assert graph["meta"]["scene_revision"] == fixture.identity(cfg)
    assert fixture.identity(Fixture(box_mass_kg=3.0)) != fixture.identity(cfg)


def test_dynamic_box_mass_contact_and_friction():
    cfg = Fixture()
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(cfg))
    data = mujoco.MjData(model)
    assert model.nq == 7 and model.nv == 6 and model.nu == 0
    assert model.body_mass[model.body("clear_box").id] == pytest.approx(cfg.box_mass_kg)
    assert model.geom_friction[model.geom("clear_box_geom").id, 0] == cfg.box_friction
    for _ in range(100):
        mujoco.mj_step(model, data)
    assert np.isfinite(data.qpos).all()
    assert data.joint("clear_box_free").qpos[2] == pytest.approx(0.35, abs=0.005)
    # Object-only impulse fixture test, NOT robotic pushing; no external force at runtime.
    data.joint("clear_box_free").qvel[0] = 0.4
    old = data.qpos[0]
    for _ in range(20):
        mujoco.mj_step(model, data)
    assert data.qpos[0] > old


def test_geometry_matches_xml():
    cfg = Fixture()
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(cfg))
    for obj in fixture.graph(cfg)["objects"]:
        if obj["id"] in ("push_goal", "robot_goal"):
            continue
        name = "clear_box_geom" if obj["id"] == "clear_box" else obj["id"]
        g = model.geom(name).id
        assert np.allclose(2 * model.geom_size[g], obj["size"])
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert np.allclose(data.geom("clear_box_geom").xpos, [*fixture.BOX_START, 0.35])


@pytest.mark.parametrize(
    "values",
    [{"box_mass_kg": -1.0}, {"box_friction": float("nan")}, {"surprise": 1}, {"clearance_m": 0.0}],
)
def test_invalid_config(values):
    with pytest.raises(ValueError):
        Fixture.model_validate(values)


def action():
    return Action(
        schema_version="clear-path-action-v1",
        action="push_object",
        state_version=0,
        object_id="clear_box",
        target_xy_m=[4.0, 1.65],
    )


def test_actions_fail_closed():
    a = action()
    with pytest.raises(ValueError, match="unavailable"):
        validate_action(a, state_version=0)
    with pytest.raises(ValueError, match="stale"):
        validate_action(a, state_version=1, enabled_actions=("push_object",))
    with pytest.raises(ValueError, match="unknown"):
        validate_action(a, state_version=0, enabled_actions=("push_object",), object_ids=())
    validate_action(a, state_version=0, enabled_actions=("push_object",))
    with pytest.raises(ValueError):
        Action.model_validate({**a.model_dump(), "target_xy_m": [float("inf"), 0.0]})


def test_oracle_invalid_not_failure():
    facts = dict(
        valid=True, goal_reached=True, path_open=True, fallen=False, forbidden_contact=False
    )
    assert evaluate(**facts)["verdict"] == "PASS"
    assert evaluate(**{**facts, "valid": False})["task_success"] is None
    for key in ("fallen", "forbidden_contact"):
        assert evaluate(**{**facts, key: True})["verdict"] == "FAIL"
    assert evaluate(**{**facts, "path_open": False})["verdict"] == "FAIL"


def test_g1_named_joint_identity_and_observation():
    source = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not source.exists():
        pytest.skip("local G1 assets unavailable")
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(Fixture(), source))
    report = audit.inspect(source, model)
    assert report["robot_joint_identity_preserved"] and report["gait_observation_equal"]
    assert report["robot_actuators"] == 29 and report["gait_observation_size"] == 86
    assert not report["active_finger_joints"]
    for palm in report["palms"]:
        assert len(palm["arm_joints"]) == 7
        assert palm["palm_collision_geom_ids"]
        assert palm["position_jacobian_rank_at_initial_pose"] == 3
