"""CPU motion, contacts, observability and static compatibility; no robot inference."""

import json
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path.audit import inspect
from clear_path.contracts import CrossingHumanFixture, HumanFixture, parse_fixture
from clear_path.human_motion import CrossingRuntime, HumanCrossing
from clear_path.humans import PROXY_ID, human_scene
from clear_path.scene_space import axes_for_schema
from robot_vlm import navigation_tools as nav
from robot_vlm.goal_policy import GoalPolicy
from robot_vlm.policy import Geometry, Observation
from robot_vlm.scene_config import validate_scene


def test_crossing_triggers_only_when_armed_and_in_range_then_stops_once():
    config = CrossingHumanFixture(corridor_width_m=3.0, human_trigger_distance_m=2.0)
    motion = HumanCrossing(config)
    start = [4.0, 1.25]
    assert motion.sample(0.0, start, armed=False)["state"] == "waiting"
    assert motion.sample(2.0, [1.0, 0.0], armed=True)["triggered_at_s"] is None
    first = motion.sample(3.0, [3.0, 0.0], armed=True)
    assert first["triggered_at_s"] == 3.0 and first["triggered_this_sample"]
    halfway = motion.sample(5.5, [1.0, 0.0], armed=True)
    assert halfway["center_xy_m"] == pytest.approx([4.0, 0.0])
    assert halfway["velocity_xy_mps"] == pytest.approx([0.0, -0.5])
    end = motion.sample(8.0, start, armed=True)
    assert end["state"] == "completed"
    assert end["center_xy_m"] == pytest.approx([4.0, -1.25])
    assert end["velocity_xy_mps"] == [0.0, 0.0]
    later = motion.sample(80.0, [4.0, -1.25], armed=True)
    assert later["center_xy_m"] == end["center_xy_m"]
    assert later["triggered_at_s"] == 3.0 and not later["triggered_this_sample"]


@pytest.mark.parametrize("side", [-1.0, 1.0])
@pytest.mark.parametrize("width", [1.6, 4.0])
def test_crossing_stays_inside_walls_and_clear_of_static_objects(side, width):
    config = CrossingHumanFixture(human_lateral_fraction=side, corridor_width_m=width)
    motion = HumanCrossing(config)
    motion.sample(0.0, [config.human_x_m, 0.0], armed=True)
    for t in np.linspace(0, 20, 21):
        row = motion.sample(float(t), [1.0, 0.0], armed=True)
        x, y = row["center_xy_m"]
        assert abs(y) + 0.2 <= width / 2 - 0.049999
        for obj in fixture.static_obstacles(config):
            if obj["id"] == PROXY_ID:
                continue
            a, b, _, _ = obj["aabb_xy_m"]
            assert x + 0.2 < a or x - 0.2 > b


@pytest.mark.parametrize(
    "change",
    [
        {"human_lateral_fraction": 0.0},
        {"human_speed_mps": 0.0},
        {"human_speed_mps": 1.51},
        {"human_speed_mps": float("nan")},
        {"human_trigger_distance_m": 0.49},
        {"human_trigger_distance_m": 5.01},
        {"footprint_radius_m": 0.4},
        {"protected_radius_m": 0.1},
    ],
)
def test_new_scene_rejects_invalid_motion_and_robot_or_measurement_changes(change):
    with pytest.raises(ValueError):
        validate_scene({"schema_version": "clear-path-crossing-human-v6", **change})


def test_nonfinite_and_backwards_clock_rejected():
    m = HumanCrossing(CrossingHumanFixture())
    m.sample(1.0, [1.0, 0.0], armed=True)
    for t, base in [(0.5, [1.0, 0.0]), (float("nan"), [1.0, 0.0]), (2.0, [float("inf"), 0.0])]:
        with pytest.raises(ValueError):
            m.sample(t, base, armed=True)


def test_static_schema_and_search_domain_remain_static_and_twenty_axes():
    config = HumanFixture()
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config))
    assert model.nmocap == 0
    assert human_scene(config)["motion_model"] == "static_proxies_piecewise_linear_base"
    assert len(axes_for_schema(config.schema_version)) == 20
    with pytest.raises(ValueError):
        parse_fixture({"schema_version": config.schema_version, "human_speed_mps": 0.5})
    # New search fixes the start side rather than sampling invalid interior starts.
    dynamic = axes_for_schema(CrossingHumanFixture().schema_version)
    assert len(dynamic) == 21 and "human_lateral_fraction" not in dynamic
    assert {"human_speed_mps", "human_trigger_distance_m"} <= dynamic.keys()


def test_new_xml_and_initial_graph_agree_without_new_joints():
    config = CrossingHumanFixture()
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(config))
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    assert model.nmocap == 1 and (model.nq, model.nv) == (7, 6)
    node = next(n for n in fixture.graph(config)["objects"] if n["id"] == PROXY_ID)
    assert node["position"] == pytest.approx(data.geom(PROXY_ID).xpos)
    assert fixture.navigation_map(config)["schema_version"] == "clear-path-map-v6"
    assert fixture.graph(config)["meta"]["human_proximity"] == human_scene(config)


def test_actual_mujoco_crossing_contacts_pose_trace_and_distance():
    # A passive free sphere stands in for a base, NOT a G1 controller. It has real
    # collision response so this exercises MuJoCo contacts, not mocked positions.
    config = CrossingHumanFixture(corridor_width_m=1.6, human_speed_mps=0.5)
    xml = fixture.world_xml(config).replace(
        "<worldbody>",
        '<worldbody><body name="test_robot" pos="4 0 0.8"><freejoint/>'
        '<geom name="test_robot_geom" type="sphere" size="0.1" mass="10"/></body>',
        1,
    )
    model = mujoco.MjModel.from_xml_string(xml)
    model.opt.gravity[:] = 0
    data = mujoco.MjData(model)
    mujoco.mj_forward(model, data)
    runtime = CrossingRuntime(config, model, data)
    world = {model.geom(name).id for name in fixture.world_geom_names(config)}
    observed_contacts = []
    for _ in range(600):
        runtime.before_step(armed=True)
        mujoco.mj_step(model, data)
        mujoco.mj_forward(model, data)
        row = runtime.after_step(world)
        assert row["time_s"] == data.time
        assert row["center_xy_m"] == pytest.approx(data.geom(PROXY_ID).xpos[:2])
        assert row["center_distance_m"] == pytest.approx(
            np.linalg.norm(data.qpos[:2] - data.geom(PROXY_ID).xpos[:2])
        )
        observed_contacts.extend(row["robot_contacts"])
    assert observed_contacts and runtime.summary()["robot_contact_steps"] > 0
    assert row["state"] == "completed"
    assert runtime.summary()["eligible_for_family_coverage"] is False


def test_actual_g1_joint_layout_and_gait_observation_unchanged():
    source = Path(
        "/workspace/g1_failure/src/GR00T-WholeBodyControl/decoupled_wbc/"
        "sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    )
    if not source.is_file():
        pytest.skip("external G1 assets unavailable")
    model = mujoco.MjModel.from_xml_string(fixture.world_xml(CrossingHumanFixture(), source))
    result = inspect(source, model)
    assert result["robot_joint_identity_preserved"] and result["gait_observation_equal"]
    assert model.nmocap == 1 and model.nu == 29


def navigation_observation(human_xy):
    return SimpleNamespace(
        base_xyz_m=[0.0, 0.0, 0.74],
        geometry=[
            SimpleNamespace(
                object_id=name, center_m=center, size_m=size, rotation_matrix=np.eye(3).ravel()
            )
            for name, center, size in [
                ("clear_floor", [0.0, 0.0, 0.0], [10.0, 10.0, 0.1]),
                (PROXY_ID, [*human_xy, 0.8], [0.4, 0.4, 1.6]),
            ]
        ],
    )


def test_follower_uses_current_human_position_during_existing_action():
    initial = navigation_observation([1.0, 2.0])
    result = {"status": "path_found", "path_xy_m": [[0.0, 0.0], [0.3, 0.0], [2.0, 0.0]]}
    session = nav.NavigationSession(initial, [2.0, 0.0], result, dynamic_geometry=True)
    current = navigation_observation([0.8, 0.0])
    session.command(current.base_xyz_m, 0.0, 2.0, lambda: current)
    assert session.rects == nav.rectangles(current)[1]
    if session.follower:
        assert session.follower.rects == nav.rectangles(current)[1]
    # At only 0.1m from the robot, entering the old forward connector is unsafe.
    blocked = navigation_observation([0.3, 0.0])
    command = session.command(blocked.base_xyz_m, 0.0, 2.1, lambda: blocked)
    assert command is None or command[0] <= 0


def test_motion_feedback_reaches_actual_policy_request():
    sample = HumanCrossing(CrossingHumanFixture()).sample(2.0, [3.0, 0.0], armed=True)
    observation = Observation(
        state_version=0,
        simulation_time_s=2.0,
        goal_xy_m=[7.0, 0.0],
        base_xyz_m=[3.0, 0.0, 0.74],
        yaw_rad=0.0,
        previous_execution="none",
        camera_name="test",
        camera_fovy_deg=65.0,
        camera_xyz_m=[3.0, 0.0, 1.0],
        camera_rotation_matrix=np.eye(3).ravel().tolist(),
        geometry=[
            Geometry(
                object_id=PROXY_ID,
                center_m=[*sample["center_xy_m"], 0.8],
                size_m=[0.4, 0.4, 1.6],
                rotation_matrix=np.eye(3).ravel().tolist(),
                semantic_role="simulated_human_proxy",
            )
        ],
        behavior_feedback={"human_motion": sample},
    )
    request = GoalPolicy().body(observation, b"\x89PNG\r\n\x1a\nmock")
    context = json.loads(request["input"][0]["content"][0]["text"])
    assert context["observation"]["behavior_feedback"]["human_motion"] == sample


@pytest.mark.parametrize("provider", ["mock", "openrouter"])
def test_runner_writes_manifest_bound_motion_and_current_observations(
    tmp_path, monkeypatch, provider
):
    """Actual runner with CPU physics and fake controller/camera/video, no inference."""
    import httpx

    from robot_vlm import goal_runner
    from robot_vlm.goal_policy import GoalMock

    groot = Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    if not (groot / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml").is_file():
        pytest.skip("external G1 assets unavailable")

    class CPUController:
        def __init__(self, *args, model, **kwargs):
            self.model = model
            self.model.opt.gravity[:] = 0
            self.command = np.zeros(3)
            # Exercise the runner's GPU-only gate with an explicit test double.
            self.execution_provider = "CUDAExecutionProvider"

        def step(self):
            mujoco.mj_step(self.model, self.data)

    class FakeRenderer:
        def __init__(self, model, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def update_scene(self, *args, **kwargs):
            pass

        def render(self):
            return np.zeros((540, 960, 3), dtype=np.uint8)

    class FakeVideo:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def append_data(self, frame):
            pass

        def close(self):
            pass

    monkeypatch.setattr(goal_runner, "G1OnnxController", CPUController)
    monkeypatch.setattr(goal_runner.mujoco, "Renderer", FakeRenderer)
    monkeypatch.setattr(goal_runner.imageio, "get_writer", lambda *a, **kw: FakeVideo())
    config = CrossingHumanFixture(human_trigger_distance_m=5.0)
    policy = GoalMock()
    if provider == "openrouter":
        monkeypatch.setenv("OPENROUTER_API_KEY", "fake-router-integration-secret")

        def handler(request):
            context = json.loads(json.loads(request.content)["messages"][1]["content"][0]["text"])
            command = {
                "state_version": context["observation"]["state_version"],
                "plan_summary": "Synthetic integration fixture",
                "action": "observe",
                "target_xy_m": None,
                "skill_request": None,
                "vx_mps": 0.0,
                "vy_mps": 0.0,
                "yaw_rate_rps": 0.0,
                "duration_s": 0.5,
            }
            return httpx.Response(
                200,
                json={
                    "id": "gen-integration",
                    "model": "openai/gpt-6-luna-pro",
                    "provider": "Azure",
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps({"command": command}),
                            },
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
                },
            )

        policy = GoalPolicy(
            model="openai/gpt-6-luna-pro",
            api_provider="openrouter",
            transport=httpx.MockTransport(handler),
        )
    result = goal_runner.run(tmp_path, groot, policy, max_calls=2, scene_config=config)
    assert result["policy_origin"] == ("openrouter_api" if provider == "openrouter" else "mock")
    assert result["api_calls_attempted"] == (2 if provider == "openrouter" else 0)
    if provider == "openrouter":
        assert result["live_actions_accepted"] == 2
        protocol = json.loads((tmp_path / "protocol.json").read_text())
        assert protocol["api_provider"] == "openrouter"
        assert protocol["routing"]["allow_fallbacks"] is False
    assert result["reason"] != "UNEXPECTED_ERROR", result
    rows = [json.loads(line) for line in (tmp_path / "human_motion.jsonl").read_text().splitlines()]
    assert all(r["triggered_at_s"] is None for r in rows if r["phase"] == "settle")
    assert any(r["triggered_at_s"] is not None for r in rows)
    assert any(abs(r["velocity_xy_mps"][1]) > 0 for r in rows)
    observation = json.loads((tmp_path / "observation_001.json").read_text())
    sample = observation["behavior_feedback"]["human_motion"]
    geometry = next(g for g in observation["geometry"] if g["object_id"] == PROXY_ID)
    assert geometry["center_m"][:2] == sample["center_xy_m"]
    assert observation["simulation_time_s"] == sample["time_s"]
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    files = {entry["path"] for entry in manifest["artifacts"]}
    assert {"human_motion.jsonl", "human_motion_summary.json", "human_proxies.json"} <= files


def test_static_archive_detector_explicitly_declines_dynamic_people(monkeypatch):
    from failure_client.evaluation import human_archive

    monkeypatch.setattr(human_archive, "verify_episode_files", lambda record: Path("/synthetic"))
    monkeypatch.setattr(
        human_archive,
        "read_json",
        lambda path: {"scene_config": CrossingHumanFixture().model_dump()},
    )
    result = human_archive.measure_archive_humans(
        SimpleNamespace(status="VALID", task_outcome="FAIL")
    )
    assert result["measurement_status"] == "UNSUPPORTED"
    assert result["reason"] == "dynamic_human_requires_separate_trajectory_detector"
    assert result["eligible_for_family_coverage"] is False
