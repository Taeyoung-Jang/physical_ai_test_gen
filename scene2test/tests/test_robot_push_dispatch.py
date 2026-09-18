import json
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from test_robot_goal_agent import obs
from test_robot_push_integration import push

from robot_vlm.push_execution import prepare
from robot_vlm.push_policy import PushPolicy


@pytest.mark.parametrize(
    "case,expected",
    [
        ("ok", None),
        ("budget", "insufficient_skill_budget"),
        ("stale", "stale_object_pose"),
        ("tilt", "unsupported_box_tilt"),
        ("far", "near_aligned_approach_required"),
        ("id", "unknown_object"),
    ],
)
def test_dispatch_preconditions(case, expected):
    model = SimpleNamespace(
        geom=lambda name: SimpleNamespace(id=0), geom_size=np.array([[0.4, 0.55, 0.35]])
    )
    data = SimpleNamespace(
        qpos=np.array([3.2, 0, 0.75, 1, 0, 0, 0]),
        geom_xpos=np.array([[4.0, 0, 0.35]]),
        geom_xmat=np.eye(3).reshape(1, 9),
    )
    observed = SimpleNamespace(
        geometry=[SimpleNamespace(object_id="clear_box_geom", center_m=[4.0, 0, 0.35])]
    )
    action = SimpleNamespace(**push())
    if case == "stale":
        data.geom_xpos[0, 0] += 0.04
    if case == "tilt":
        data.geom_xmat[0, 8] = 0.9
    if case == "far":
        data.qpos[0] = 1
    if case == "id":
        action.object_id = "wall"
    before = data.qpos.copy(), data.geom_xpos.copy()
    session, result = prepare(model, data, action, observed, 10 if case == "budget" else 30)
    assert (None if result is None else result["reason"]) == expected
    assert (session is not None) == (case == "ok")
    assert np.array_equal(before[0], data.qpos) and np.array_equal(before[1], data.geom_xpos)


def test_mock_api_push_and_feedback(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-key")
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [
                            {"type": "output_text", "text": json.dumps({"command": push(1)})}
                        ],
                    }
                ],
            },
        )

    policy = PushPolicy(transport=httpx.MockTransport(handler))
    action, _ = policy.decide(obs(), b"\x89PNG\r\n\x1a\nmock")
    assert action.action == "push_object"
    policy.feedback(action, {"status": "rejected", "reason": "near_aligned_approach_required"})
    body = policy.body(obs(), b"\x89PNG\r\n\x1a\nmock")
    context = json.loads(body["input"][0]["content"][0]["text"])
    assert "push_object" in context["capabilities"]
    assert context["history"][-1]["execution"]["status"] == "rejected"
    assert len(requests) == 1
