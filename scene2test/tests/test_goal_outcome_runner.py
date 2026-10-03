"""Run the actual orchestration loop with real CPU MuJoCo contacts and test doubles.

The scripted state changes below are test inputs, NOT simulated G1 ability/GPU evidence.
No network, ONNX loading, graphics context or external runtime writes.
"""

import json
import weakref
import xml.etree.ElementTree as ET
from concurrent.futures import Future
from types import SimpleNamespace

import mujoco
import numpy as np
import pytest

from clear_path import fixture
from robot_vlm import goal_runner as runner
from robot_vlm.goal_policy import GoalAction
from robot_vlm.policy import PolicyError
from robot_vlm.push_policy import PushAction, PushMock


def setup_loop(monkeypatch, scenario):
    original_xml = fixture.world_xml

    def xml(config, source):
        root = ET.fromstring(original_xml(config))
        root.find("option").set("timestep", ".05")
        body = ET.fromstring("""<body name="pelvis" pos="3.2 0 .74">
          <freejoint/><geom name="test_hand" type="sphere" size=".1" mass="1"/>
          <camera name="clear_robot_camera" pos="0 0 .3"/>
          <site name="left_push_site"/><site name="right_push_site"/>
        </body>""")
        root.find("worldbody").insert(0, body)
        return ET.tostring(root, encoding="unicode")

    monkeypatch.setattr(fixture, "world_xml", xml)
    monkeypatch.setattr(runner.audit, "inspect", lambda *args: {"test_double": True})
    monkeypatch.setattr(runner.audit, "initial_data", lambda model, source: mujoco.MjData(model))

    class Controller:
        execution_provider = "CUDAExecutionProvider"  # bypass loader only; not real CUDA evidence
        counter = 0
        command = np.zeros(3)
        upper_target = np.zeros(1)

        def __init__(self, *args, **kwargs):
            pass

        def arm_targets(self, goals):
            pass

        def step(self):
            self.counter += 1
            self.data.time = round(self.data.time + 0.05, 8)
            t = self.data.time
            if scenario.startswith("recovery_"):
                self.data.qpos[:3] = [3.205, 0, 0.74]  # frozen shallow .395m box clearance
            elif scenario.startswith("nav_") and t >= 2.05:
                if scenario == "nav_leave" and 3.0 <= t < 3.3:
                    self.data.qpos[:3] = [6.6, 0, 0.74]
                elif scenario != "nav_never_arrive":
                    self.data.qpos[:3] = [6.8 if t < 2.8 else 6.9, 0, 0.74]
            elif scenario == "numerical" and t > 2:
                self.data.qpos[0] = float("nan")
            elif scenario == "fall_recover" and 2 < t < 2.4:
                self.data.qpos[2] = 0.3
            elif scenario.startswith("contact") and 2 < t < 2.4:
                self.data.qpos[0] = 4.0
            elif scenario == "obstacle_contact_goal" and 2 < t < 2.4:
                self.data.qpos[:3] = [2.5, 0, 0.3]
            elif scenario in {"fall_recover", "contact_goal", "obstacle_contact_goal"} and t >= 2.4:
                self.data.qpos[:3] = [7, 0, 0.74]
            elif scenario == "push_handoff_goal" and 20 < t < 20.3:
                self.data.qpos[0] = 4.0
            elif scenario == "push_handoff_goal" and 20.3 <= t < 23.1:
                self.data.qpos[0] = 3.2
            elif scenario == "push_goal_early" and t >= 3.1:
                self.data.qpos[:3] = [7, 0, 0.74]
            elif scenario.startswith("push_") and t >= 23.1:
                self.data.qpos[:3] = [7, 0, 0.74]

    monkeypatch.setattr(runner, "G1OnnxController", Controller)
    from clear_path import push_probe
    from robot_vlm import push_execution

    monkeypatch.setattr(push_probe, "ArmGaitController", Controller)

    class PushSession:
        control = SimpleNamespace(released=scenario != "push_failure_goal", phase="push")

        def command(self, *args):
            return {}, np.zeros(3)

        def observe_contact(self, *args):
            pass

        def result(self, *args, **kwargs):
            return {"success": False, "status": "failed", "reason": "target_not_reached"}

    monkeypatch.setattr(push_execution, "prepare", lambda *args: (PushSession(), None))
    monkeypatch.setattr(push_execution, "measure", lambda *args: {"test_double": True})

    class Renderer:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def update_scene(self, *args, **kwargs):
            pass

        def render(self):
            return np.zeros((32, 32, 3), dtype=np.uint8)

    class Writer(Renderer):
        def append_data(self, *args):
            pass

        def close(self):
            pass

    monkeypatch.setattr(runner.mujoco, "Renderer", Renderer)
    monkeypatch.setattr(runner.imageio, "get_writer", Writer)

    def unexpected_gif(*args, **kwargs):
        pytest.fail("GIF writing must remain disabled")

    monkeypatch.setattr(runner.imageio, "mimsave", unexpected_gif)
    monkeypatch.setattr(runner.time, "sleep", lambda *args: None)

    class Executor:
        def __init__(self, *args, **kwargs):
            pass

        def submit(self, fn, *args):
            future = Future()
            if scenario != "inference_budget":
                try:
                    future.set_result(fn(*args))
                except Exception as exc:
                    future.set_exception(exc)
            return future

        def shutdown(self, **kwargs):
            pass

    monkeypatch.setattr(runner, "ThreadPoolExecutor", Executor)

    class Script(PushMock):
        observations = []

        def decide(self, obs, png):
            self.observations.append(obs)
            if scenario == "api_error":
                raise PolicyError("transport_error")
            value = dict(
                state_version=obs.state_version,
                plan_summary="test only",
                action="observe",
                target_xy_m=None,
                skill_request=None,
                vx_mps=0.0,
                vy_mps=0.0,
                yaw_rate_rps=0.0,
                duration_s=2.0,
            )
            if scenario.startswith("nav_"):
                value.update(
                    action="navigate_to",
                    target_xy_m=[6.9, 0.0] if scenario == "nav_waypoint" else [7.0, 0.0],
                    duration_s=0.85 if scenario == "nav_short" else 3.0,
                )
                if scenario == "nav_stop":
                    value.update(action="stop", target_xy_m=None)
            if scenario.startswith("recovery_") and obs.state_version == 0:
                value.update(
                    action="plan_path" if scenario == "recovery_query" else "navigate_to",
                    target_xy_m=[7.0, 0.0],
                    duration_s=3.0,
                )
            if scenario in {"move_zero", "move_lateral"}:
                value.update(action="move", vy_mps=0.1 if scenario == "move_lateral" else 0.0)
            if scenario.startswith("push_") and obs.state_version == 0:
                value.update(
                    action="push_object",
                    object_id="clear_box_geom",
                    target_xy_m=[4.08, 0.0],
                    duration_s=18.0,
                )
                return PushAction(**value), {"origin": "mock"}
            return GoalAction(**value), {"origin": "mock"}

    return Script()


@pytest.mark.parametrize("scenario,expected_vy", [("move_zero", 0.0), ("move_lateral", 0.1)])
def test_numeric_move_feedback_reaches_next_policy_without_rewrite_or_extra_call(
    monkeypatch, tmp_path, scenario, expected_vy
):
    policy = setup_loop(monkeypatch, scenario)
    result = runner.run(tmp_path, tmp_path, policy, max_calls=2)
    assert (result["task_outcome"], result["reason"]) == ("FAIL", "BUDGET_EXHAUSTED")
    assert result["calls_attempted"] == 2
    rows = [json.loads(s) for s in (tmp_path / "states.jsonl").read_text().splitlines()]
    assert all(
        r["command"] == pytest.approx([0, expected_vy, 0]) for r in rows if r["phase"] == "move"
    )
    context = json.loads((tmp_path / "goal_context_001.json").read_text())
    feedback = context["execution_feedback"]
    assert feedback["recent_consecutive_zero_move_commands"] == (1 if expected_vy == 0 else 0)
    assert feedback["last_motion"]["elapsed_s"] == 2
    assert feedback["last_motion"]["net_translation_m"] == 0  # scripted fixed pose
    assert policy.memory[-1]["execution"]["motion"]["raw_move_command_body"] == [0, expected_vy, 0]
    protocol = json.loads((tmp_path / "protocol.json").read_text())
    assert protocol["navigation_follower"]["version"] == "clearance-recovery-v3"
    assert "execution_feedback" in protocol["source_hashes"]


@pytest.mark.parametrize(
    "scenario,profile,max_seconds,outcome,reason",
    [
        ("nav_arrive", "position_only_v1", None, "FAIL", "BUDGET_EXHAUSTED"),
        ("nav_arrive", "goal_dwell_v1", None, "PASS", "GOAL_REACHED"),
        ("nav_short", "goal_dwell_v1", None, "FAIL", "BUDGET_EXHAUSTED"),
        ("nav_arrive", "goal_dwell_v1", 3, "FAIL", "SIMULATION_BUDGET"),
        ("nav_leave", "goal_dwell_v1", None, "PASS", "GOAL_REACHED"),
        ("nav_waypoint", "goal_dwell_v1", None, "FAIL", "BUDGET_EXHAUSTED"),
        ("nav_never_arrive", "goal_dwell_v1", None, "FAIL", "BUDGET_EXHAUSTED"),
        ("nav_no_path", "goal_dwell_v1", None, "FAIL", "BUDGET_EXHAUSTED"),
        ("nav_stop", "goal_dwell_v1", None, "FAIL", "POLICY_STOP"),
    ],
)
def test_final_navigation_contract_is_bounded_and_goal_independent(
    monkeypatch, tmp_path, scenario, profile, max_seconds, outcome, reason
):
    policy = setup_loop(monkeypatch, scenario)

    # The route/state are scripted to test the actual runner, not G1 capabilities.
    # This completion-contract fixture deliberately jumps through a box. Stub
    # following too; real geometry/recovery is exercised in dedicated tests.
    def scripted_follow(self, base, heading):
        self.last = {"status": "tracking", "command_body": [0.1, 0, 0]}
        return [0.1, 0, 0]

    monkeypatch.setattr(runner.navigation_tools.PathFollower, "command", scripted_follow)
    monkeypatch.setattr(
        runner.navigation_tools,
        "plan",
        lambda obs, target: {
            "status": "no_path" if scenario == "nav_no_path" else "path_found",
            "path_xy_m": [] if scenario == "nav_no_path" else [list(target)],
        },
    )
    result = runner.run(
        tmp_path,
        tmp_path,
        policy,
        max_calls=1,
        max_seconds=max_seconds,
        navigation_completion=profile,
    )
    assert (result["task_outcome"], result["reason"]) == (outcome, reason), result
    assert result["calls_attempted"] == 1
    diagnostic = json.loads((tmp_path / "terminal_diagnostics.json").read_text())
    assert diagnostic["policy_calls_remaining"] == 0
    assert diagnostic["goal_progress"] == result["goal_progress"]
    assert diagnostic["navigation_completion"]["post_budget_grace_s"] == 0
    if diagnostic["last_navigation"]:
        assert result["duration_s"] <= diagnostic["last_navigation"]["action_deadline_s"] + 1e-8
    if scenario == "nav_never_arrive":
        rows = [json.loads(s) for s in (tmp_path / "states.jsonl").read_text().splitlines()]
        samples = [r for r in rows if r["phase"] == "navigate_to"]
        assert samples and all(r["navigation_tracking"] is not None for r in samples)
        assert policy.memory[-1]["execution"]["motion"]["samples"] > 0
    protocol = json.loads((tmp_path / "protocol.json").read_text())
    assert protocol["navigation_completion"]["profile"] == profile
    assert "navigation_completion" in protocol["source_hashes"]
    if scenario == "nav_arrive" and profile == "position_only_v1":
        assert result["goal_progress"]["current_dwell_s"] == pytest.approx(0.75)
        assert result["duration_s"] == pytest.approx(2.8)
        assert diagnostic["budget_ended_during_goal_dwell"]
    if outcome == "PASS":
        assert result["duration_s"] == pytest.approx(4.3 if scenario == "nav_leave" else 3.05)
        assert result["goal_progress"]["current_dwell_s"] == pytest.approx(1.0)
        assert diagnostic["last_navigation"]["hold_simulation_s"] > 0
        assert not diagnostic["budget_ended_during_goal_dwell"]
    if scenario == "nav_waypoint":
        assert not diagnostic["last_navigation"]["goal_dwell_enabled_for_target"]
        assert diagnostic["last_navigation"]["hold_simulation_s"] == 0
    if scenario == "nav_no_path":
        assert diagnostic["last_navigation"]["status"] == "no_path"
        assert diagnostic["last_navigation"]["hold_simulation_s"] == 0
    assert not (tmp_path / "rollout.gif").exists()


def test_navigation_profile_rejects_legacy_guard_before_assets(tmp_path):
    with pytest.raises(ValueError, match="requires goal_outcome_v1"):
        runner.run(
            tmp_path,
            tmp_path,
            None,
            navigation_completion="goal_dwell_v1",
            evaluation_profile="legacy_guarded",
        )
    assert not list(tmp_path.iterdir())


def test_planner_refreshes_geometry_after_model_observation(monkeypatch, tmp_path):
    policy = setup_loop(monkeypatch, "nav_never_arrive")
    original = policy.decide

    def stale_geometry(obs, png):
        value = original(obs, png)
        # Simulate an obsolete camera-time geometry snapshot. The real execution
        # must use current MuJoCo geometry, not these stale coordinates.
        for geom in obs.geometry:
            if geom.object_id == "clear_box_geom":
                geom.center_m[0] = 100.0
        return value

    policy.decide = stale_geometry
    planned = []

    def planner(obs, target):
        planned.append(obs)
        return {"status": "no_path", "path_xy_m": []}

    monkeypatch.setattr(runner.navigation_tools, "plan", planner)
    result = runner.run(tmp_path, tmp_path, policy, max_calls=1)
    assert result["task_outcome"] == "FAIL" and result["calls_attempted"] == 1
    assert len(planned) == 1
    geom = next(g for g in planned[0].geometry if g.object_id == "clear_box_geom")
    assert geom.center_m[0] == pytest.approx(4.0)
    context = json.loads((tmp_path / "navigation_context_000.json").read_text())
    assert context["geometry"] == [g.model_dump() for g in planned[0].geometry]


@pytest.mark.parametrize(
    "duration,simulation_cap,expected_status",
    [
        (3.0, None, "recovery_no_progress"),
        (0.35, None, "execution_slice_ended"),
        (3.0, 3.0, "execution_slice_ended"),
    ],
)
def test_actual_recovery_loop_respects_action_and_episode_budget(
    monkeypatch, tmp_path, duration, simulation_cap, expected_status
):
    from clear_path.contracts import CorridorFixture

    policy = setup_loop(monkeypatch, "recovery_frozen")
    decide = policy.decide

    def short_action(obs, png):
        action, raw = decide(obs, png)
        return action.model_copy(update={"duration_s": duration}), raw

    policy.decide = short_action
    result = runner.run(
        tmp_path,
        tmp_path,
        policy,
        max_calls=1,
        max_seconds=simulation_cap,
        scene_config=CorridorFixture(corridor_width_m=4).model_dump(),
        navigation_completion="goal_dwell_v1",
    )
    assert result["task_outcome"] == "FAIL" and result["valid_execution"]
    assert result["calls_attempted"] == 1
    feedback = policy.memory[0]["execution"]
    assert feedback["status"] == expected_status
    assert feedback["navigation_recovery"]["recovery_count"] == 1
    assert feedback["navigation_recovery"]["replan_count"] == 0
    assert feedback["motion"]["elapsed_s"] <= min(duration, 1.05) + 1e-8
    if simulation_cap is not None:
        assert result["duration_s"] <= simulation_cap
        assert result["reason"] == "SIMULATION_BUDGET"
    else:
        assert result["reason"] == "BUDGET_EXHAUSTED"
    trace = json.loads((tmp_path / "navigation_trace_000.json").read_text())
    assert trace["target_xy_m"] == [7, 0] and trace["summary"] == feedback["navigation_recovery"]
    artifacts = json.loads((tmp_path / "manifest.json").read_text())["artifacts"]
    assert "navigation_trace_000.json" in {r["path"] for r in artifacts}
    assert not (tmp_path / "rollout.gif").exists()


@pytest.mark.parametrize("scenario", ["recovery_frozen", "recovery_query"])
def test_recovery_diagnostic_reaches_next_policy_and_query_never_recovers(
    monkeypatch, tmp_path, scenario
):
    from clear_path.contracts import CorridorFixture

    policy = setup_loop(monkeypatch, scenario)
    captured_inputs = []
    decide = policy.decide

    def capture_input(obs, png):
        body = policy.body(obs, png)
        captured_inputs.append(json.loads(body["input"][0]["content"][0]["text"]))
        return decide(obs, png)

    policy.decide = capture_input
    result = runner.run(
        tmp_path,
        tmp_path,
        policy,
        max_calls=2,
        scene_config=CorridorFixture(corridor_width_m=4).model_dump(),
    )
    assert result["calls_attempted"] == 2 and result["task_outcome"] == "FAIL"
    feedback = captured_inputs[1]["history"][0]["execution"]
    if scenario == "recovery_frozen":
        assert feedback["status"] == "recovery_no_progress"
        assert feedback["navigation_recovery"]["events"][-1]["reason"] == "recovery_no_progress"
    else:
        assert feedback["status"] == "blocked_endpoint"
        assert "navigation_recovery" not in feedback
        assert not (tmp_path / "navigation_trace_000.json").exists()


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("contact_goal", "PASS"),
        ("fall_recover", "PASS"),
        ("contact_budget", "FAIL"),
        ("push_failure_goal", "PASS"),
        ("push_handoff_goal", "PASS"),
        ("push_goal_early", "PASS"),
        ("numerical", "INCONCLUSIVE"),
        ("api_error", "INCONCLUSIVE"),
        ("inference_budget", "FAIL"),
    ],
)
def test_real_runner_goal_semantics(monkeypatch, tmp_path, scenario, expected):
    policy = setup_loop(monkeypatch, scenario)
    result = runner.run(
        tmp_path,
        tmp_path,
        policy,
        max_calls=2 if scenario.startswith("push_") else 1,
        enable_push=scenario.startswith("push_"),
        max_seconds=3 if scenario == "inference_budget" else None,
    )
    assert result["task_outcome"] == expected, result
    assert json.loads((tmp_path / "result.json").read_text()) == result
    assert (tmp_path / "manifest.json").exists()
    assert not (tmp_path / "rollout.gif").exists()
    assert "href='rollout.gif'" not in (tmp_path / "report.html").read_text()
    if scenario == "contact_goal":
        contacts = [
            json.loads(line) for line in (tmp_path / "contacts.jsonl").read_text().splitlines()
        ]
        unexpected = [c for c in contacts if not c["legacy_allowed"]]
        assert unexpected and all(c["normal_force_n"] is not None for c in unexpected)
        assert all("effective_friction" in c for c in unexpected)
    if scenario == "fall_recover":
        assert result["events_summary"]["counts"]["upright_recovered"] == 1
    if scenario == "push_handoff_goal":
        contacts = [
            json.loads(line) for line in (tmp_path / "contacts.jsonl").read_text().splitlines()
        ]
        assert any(c["phase"] == "push_handoff" and not c["legacy_allowed"] for c in contacts)
        skill = json.loads((tmp_path / "skill_000.json").read_text())
        assert skill["handoff_complete"] and result["calls_attempted"] == 2
    if scenario == "push_failure_goal":
        skill = json.loads((tmp_path / "skill_000.json").read_text())
        assert skill["reason"] == "SKILL_RELEASE_FAILURE" and skill["handoff_complete"]
        assert result["calls_attempted"] == 2
        assert policy.observations[1].behavior_feedback["summary"]["counts"]["skill_failure"] == 1
    if scenario == "push_goal_early":
        assert result["calls_attempted"] == 1
        assert result["events_summary"]["counts"]["skill_interrupted"] == 1
        assert result["events_summary"]["counts"].get("skill_failure", 0) == 0
    if scenario == "inference_budget":
        assert result["reason"] == "INFERENCE_SIM_BUDGET" and result["valid_execution"]


def test_legacy_guard_truncates_and_is_not_new_goal_failure(monkeypatch, tmp_path):
    policy = setup_loop(monkeypatch, "contact_goal")
    result = runner.run(
        tmp_path, tmp_path, policy, max_calls=1, evaluation_profile="legacy_guarded"
    )
    assert result["reason"] == "FORBIDDEN_CONTACT"
    assert result["task_outcome"] == "INCONCLUSIVE"
    assert result["termination"]["actor"] == "legacy_guard"


def test_explicit_simulation_budget_stops_action(monkeypatch, tmp_path):
    policy = setup_loop(monkeypatch, "budget")
    result = runner.run(tmp_path, tmp_path, policy, max_calls=1, max_seconds=3)
    assert result["task_outcome"] == "FAIL" and result["reason"] == "SIMULATION_BUDGET"
    assert result["duration_s"] == pytest.approx(3)


def test_real_mp4_stream_does_not_retain_frame_history(monkeypatch, tmp_path):
    # Exercise the installed ffmpeg writer, unlike the physics-only tests above.
    original_writer = runner.imageio.get_writer
    policy = setup_loop(monkeypatch, "budget")
    frame_refs = []

    class StreamingWriter:
        def __init__(self, *args, **kwargs):
            self.writer = original_writer(*args, **kwargs)

        def __enter__(self):
            self.writer.__enter__()
            return self

        def __exit__(self, *args):
            return self.writer.__exit__(*args)

        def append_data(self, frame):
            frame_refs.append(weakref.ref(frame))
            self.writer.append_data(frame)
            # A small encoder working set is fine; an episode-wide list is not.
            assert sum(ref() is not None for ref in frame_refs) <= 3

        def close(self):
            self.writer.close()

    monkeypatch.setattr(runner.imageio, "get_writer", StreamingWriter)
    result = runner.run(tmp_path, tmp_path, policy, max_calls=1, max_seconds=3)
    assert result["reason"] == "SIMULATION_BUDGET", result
    assert len(frame_refs) >= 30
    assert all(ref() is None for ref in frame_refs)
    assert (tmp_path / "rollout.mp4").stat().st_size > 0
    with runner.imageio.get_reader(tmp_path / "rollout.mp4") as video:
        assert video.get_meta_data()["fps"] == 12
        assert video.get_data(0).shape[:2] == (32, 32)
    assert not (tmp_path / "rollout.gif").exists()
    protocol = json.loads((tmp_path / "protocol.json").read_text())
    assert protocol["recording"]["gif_enabled"] is False
    assert protocol["recording"]["retain_frame_history"] is False
    assert protocol["max_output_tokens_per_call"] is None
    assert protocol["output_token_limit_policy"] == "provider_default_no_client_cap"
    assert json.loads((tmp_path / "result.json").read_text()) == result
    artifacts = json.loads((tmp_path / "manifest.json").read_text())["artifacts"]
    assert {"result.json", "report.html", "rollout.mp4"} <= {r["path"] for r in artifacts}


def test_corridor_scene_reaches_actual_runner_observation_without_reference_path(
    monkeypatch, tmp_path
):
    from clear_path.contracts import CorridorFixture

    policy = setup_loop(monkeypatch, "budget")
    config = CorridorFixture(corridor_width_m=2.4, box_lateral_fraction=1.0)
    result = runner.run(
        tmp_path, tmp_path, policy, max_calls=1, scene_config=config.model_dump(), enable_push=True
    )
    # The controller and policy are doubles; this checks wiring, not physical success.
    assert result["task_outcome"] == "FAIL"
    obs = policy.observations[0]
    geometry = {g.object_id: g for g in obs.geometry}
    assert geometry["wall_north"].center_m[1] == pytest.approx(1.25)
    assert geometry["clear_box_geom"].center_m[1] == pytest.approx(0.6)
    assert "bay_north" not in geometry
    assert obs.goal_xy_m == [7.0, 0.0]
    body = policy.body(obs, b"\x89PNG\r\n\x1a\ntest")
    context = json.loads(body["input"][0]["content"][0]["text"])
    assert "reference_path" not in context and "afs_failure_hypothesis" not in context
    protocol = json.loads((tmp_path / "protocol.json").read_text())
    assert protocol["scene_config"] == config.model_dump()
    assert not protocol["reference_path_provided"]
    assert json.loads((tmp_path / "navigation_map.json").read_text())["reachable"]
    assert json.loads((tmp_path / "scene_graph.json").read_text())["meta"][
        "scene_revision"
    ] == fixture.identity(config)
    artifacts = json.loads((tmp_path / "manifest.json").read_text())["artifacts"]
    assert {"scene_graph.json", "navigation_map.json"} <= {r["path"] for r in artifacts}


def test_oriented_obstacles_reach_robot_observation_not_just_evaluator(monkeypatch, tmp_path):
    from clear_path.contracts import ObstacleFixture
    from clear_path.obstacles import static_obstacles

    policy = setup_loop(monkeypatch, "budget")
    config = ObstacleFixture(obstacle_1_yaw_deg=37.0, obstacle_2_height_m=0.1)
    result = runner.run(
        tmp_path, tmp_path, policy, max_calls=1, scene_config=config.model_dump(), enable_push=True
    )
    assert result["task_outcome"] == "FAIL"  # synthetic budget stop, not a geometry oracle
    obs = policy.observations[0]
    geometry = {g.object_id: g for g in obs.geometry}
    assert set(geometry) == set(fixture.world_geom_names(config))
    for row in static_obstacles(config):
        geom = geometry[row["id"]]
        assert geom.center_m == pytest.approx(row["center_m"])
        assert geom.size_m == pytest.approx(row["local_size_m"])
        assert geom.rotation_matrix == pytest.approx(row["rotation_matrix"])
    assert obs.goal_xy_m == [7.0, 0.0]
    body = policy.body(obs, b"\x89PNG\r\n\x1a\ntest")
    ctx = json.loads(body["input"][0]["content"][0]["text"])
    assert "reference_path" not in ctx and "afs_failure_hypothesis" not in ctx
    assert not (tmp_path / "rollout.gif").exists()


def test_new_obstacle_contact_is_recorded_but_not_automatic_goal_failure(monkeypatch, tmp_path):
    from clear_path.contracts import ObstacleFixture

    policy = setup_loop(monkeypatch, "obstacle_contact_goal")
    config = ObstacleFixture(obstacle_1_lateral_fraction=0.0)
    result = runner.run(
        tmp_path, tmp_path, policy, max_calls=1, scene_config=config.model_dump(), enable_push=True
    )
    contacts = [json.loads(line) for line in (tmp_path / "contacts.jsonl").read_text().splitlines()]
    assert any(c["world_geom_name"] == "obstacle_1" for c in contacts)
    assert result["task_outcome"] == "PASS"  # recovery/arrival scripted; no real gait claim
