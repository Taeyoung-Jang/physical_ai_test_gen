import json
import math

import httpx
import mujoco
import numpy as np
import pytest

from clear_path import fixture
from clear_path.contracts import Fixture
from robot_vlm.goal_policy import GoalAction, GoalPolicy
from robot_vlm.navigation_tools import follow_command, hold_command, plan
from robot_vlm.policy import Geometry, Observation


def obs():
    m = mujoco.MjModel.from_xml_string(fixture.world_xml(Fixture()))
    d = mujoco.MjData(m)
    mujoco.mj_forward(m, d)
    return Observation(
        state_version=1,
        simulation_time_s=2.0,
        goal_xy_m=[7.0, 0.0],
        base_xyz_m=[1.0, 0.0, 0.74],
        yaw_rad=0.0,
        previous_execution="none",
        camera_name="test",
        camera_fovy_deg=65.0,
        camera_xyz_m=[1.0, 0.0, 1.0],
        camera_rotation_matrix=np.eye(3).ravel().tolist(),
        geometry=[
            Geometry(
                object_id=m.geom(g).name,
                center_m=d.geom_xpos[g].tolist(),
                size_m=(2 * m.geom_size[g]).tolist(),
                rotation_matrix=d.geom_xmat[g].tolist(),
            )
            for g in range(m.ngeom)
        ],
    )


def action(**kw):
    return GoalAction.model_validate(
        dict(
            state_version=1,
            plan_summary="Choose my own subgoal",
            action="navigate_to",
            target_xy_m=[1.4, 0.0],
            skill_request=None,
            vx_mps=0.0,
            vy_mps=0.0,
            yaw_rate_rps=0.0,
            duration_s=3.0,
        )
        | kw
    )


def test_robot_planner_reachable_blocked_and_outside():
    o = obs()
    path = plan(o, [1.4, 0.0])
    assert path["status"] == "path_found" and len(path["path_xy_m"]) > 1
    assert plan(o, [7.0, 0.0])["status"] == "no_path"
    assert plan(o, [4.0, 0.0])["status"] == "blocked_endpoint"
    assert plan(o, [100.0, 0.0])["status"] == "blocked_endpoint"


def test_hold_world_to_body_and_angle_wrap():
    assert hold_command([0, 0, 0], math.pi / 2, [0.1, 0, 0], math.pi / 2)[:2] == pytest.approx(
        [0, -0.08]
    )
    assert abs(hold_command([0, 0, 0], math.pi - 0.01, [0, 0, 0], -math.pi + 0.01)[2] - 0.02) < 1e-8
    assert max(abs(v) for v in hold_command([0, 0, 0], 0, [100, 100, 0], 0)) <= 0.12


def test_follower_turns_without_forward_into_opposite_direction():
    cmd = follow_command([1, 0, 0], math.pi, [[1.5, 0]])
    assert cmd[0] == 0 and abs(cmd[2]) <= 0.4


@pytest.mark.parametrize(
    "kw",
    [
        {"target_xy_m": None},
        {"target_xy_m": [1.0]},
        {"target_xy_m": [float("nan"), 0.0]},
        {"vx_mps": 0.1},
        {"action": "move", "target_xy_m": None, "duration_s": 3.0},
    ],
)
def test_invalid_tool_arguments(kw):
    with pytest.raises(ValueError):
        action(**kw)


def test_memory_capabilities_and_model_transport(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body)
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-6-astra",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps({"command": action().model_dump()}),
                            }
                        ],
                    }
                ],
            },
        )

    p = GoalPolicy(transport=httpx.MockTransport(handler))
    for _ in range(10):
        p.feedback(action(), {"status": "no_path"})
    result, _ = p.decide(obs(), b"\x89PNG\r\n\x1a\nmock")
    assert result == action()
    context = json.loads(seen[0]["input"][0]["content"][0]["text"])
    assert len(context["history"]) == 8 and "plan_path" in context["capabilities"]
    assert "no path planner" not in json.dumps(seen[0])
    assert seen[0]["reasoning"]["effort"] == "high"
    assert "afs" not in context


def test_unsupported_skill_can_be_expressed_without_fake_execution():
    a = action(action="request_skill", target_xy_m=None, skill_request="move the box sideways")
    assert a.action == "request_skill"
