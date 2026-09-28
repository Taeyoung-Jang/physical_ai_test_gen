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
            if scenario == "numerical" and t > 2:
                self.data.qpos[0] = float("nan")
            elif scenario == "fall_recover" and 2 < t < 2.4:
                self.data.qpos[2] = 0.3
            elif scenario.startswith("contact") and 2 < t < 2.4:
                self.data.qpos[0] = 4.0
            elif scenario in {"fall_recover", "contact_goal"} and t >= 2.4:
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
