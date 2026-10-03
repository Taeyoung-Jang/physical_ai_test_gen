import json
from types import SimpleNamespace

import numpy as np
import pytest
from test_robot_push_integration import push

from robot_vlm.push_alignment import Alignment, readiness
from robot_vlm.push_execution import align


def state(base, yaw=0):
    return readiness(
        np.array(base), yaw, np.array([4.0, 0, 0.35]), 0, np.array([0.8, 1.1, 0.7]), [4.15, 0.0]
    )


def test_saved_failure_geometry_and_json_feedback():
    before = state([3.17543865, -0.03596943, 0.74166])
    after = state([3.17997032, -0.07171399, 0.74222])
    assert before["ready"] and not after["ready"] and after["correctable"]
    assert after["measured"]["lateral_error_m"] == pytest.approx(0.07171399)
    assert after["limits"]["lateral_error_abs_m"] == 0.06
    json.dumps(after, allow_nan=False)


def test_bounded_direction_stability_and_timeout():
    base = [3.18, -0.072, 0.74]
    control = Alignment(base, 0)
    status, cmd = control.update(0, base, 0, state(base))
    assert status == "aligning" and 0 < cmd[1] <= 0.08
    good = [3.18, -0.02, 0.74]
    assert control.update(1, good, 0, state(good))[0] == "aligning"
    assert control.update(1.26, good, 0, state(good))[0] == "aligned"
    assert Alignment(base, 0).update(8, base, 0, state(base))[0] == "alignment_timeout"


def test_stability_resets_and_out_of_range_stops():
    good, bad = [3.18, -0.02, 0.74], [3.18, -0.07, 0.74]
    a = Alignment(good, 0)
    a.update(0, good, 0, state(good))
    a.update(0.2, bad, 0, state(bad))
    assert a.update(0.3, good, 0, state(good))[0] == "aligning"
    far = [3.18, -0.2, 0.74]
    assert Alignment(far, 0).update(0, far, 0, state(far))[0] == "alignment_out_of_range"


def test_motion_bound():
    a = Alignment([3.18, -0.07, 0.74], 0)
    for t in range(10):
        base = [3.18, -0.07 if t % 2 else 0.07, 0.74]
        status, _ = a.update(t * 0.01, base, 0, state(base))
        if status == "alignment_motion_limit":
            break
    assert status == "alignment_motion_limit"


@pytest.mark.parametrize("mode", ["converge", "stuck", "safety", "budget", "object_moved"])
@pytest.mark.parametrize("push_distance", [0.15, 0.20])
def test_guarded_dispatch_with_fake_kinematics_only(mode, push_distance):
    # Not a MuJoCo/GPU rollout: deterministic callback tests orchestration only.
    model = SimpleNamespace(
        geom=lambda name: SimpleNamespace(id=0), geom_size=np.array([[0.4, 0.55, 0.35]])
    )
    data = SimpleNamespace(
        qpos=np.array([3.18, -0.0717, 0.74, 1.0, 0, 0, 0]),
        geom_xpos=np.array([[4.0, 0, 0.35]]),
        geom_xmat=np.eye(3).reshape(1, 9),
        time=0.0,
    )
    observation = SimpleNamespace(
        geometry=[SimpleNamespace(object_id="clear_box_geom", center_m=[4.0, 0, 0.35])]
    )
    rows = []

    def step(cmd):
        data.time += 0.01
        if mode == "converge":
            data.qpos[:2] += np.array(cmd[:2]) * 0.01
        if mode == "object_moved":
            data.geom_xpos[0, 0] += 0.04

    session, feedback, summary = align(
        model,
        data,
        SimpleNamespace(**push(target=[4.0 + push_distance, 0.0])),
        observation,
        25 if mode == "budget" else 40,
        step,
        lambda: mode == "safety" and data.time > 0.02,
        rows.append,
    )
    if mode == "converge":
        assert session is not None and summary["status"] == "aligned"
        assert feedback is None and data.time < 8
    else:
        assert session is None
        expected = {
            "stuck": "alignment_timeout",
            "safety": "alignment_safety_stop",
            "budget": "alignment_insufficient_budget",
            "object_moved": "stale_object_pose",
        }
        assert feedback["reason"] == expected[mode]
    json.dumps(summary, allow_nan=False)
