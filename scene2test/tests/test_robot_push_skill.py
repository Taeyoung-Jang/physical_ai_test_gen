import math

import numpy as np
import pytest

from robot_vlm.push_skill import PushSession, preflight


def inputs():
    return dict(
        base=np.array([3.2, 0.0, 0.75]),
        yaw=0.0,
        box=np.array([4.0, 0.0, 0.35]),
        box_yaw=0.0,
        size=[0.8, 1.1, 0.7],
        target=[4.08, 0.0],
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"base": [1, 0, 0.75]}, "near_aligned_approach_required"),
        ({"yaw": 1.0}, "approach_heading_required"),
        ({"target": [4, 1.65]}, "unsupported_push_distance"),
        ({"size": [0.1, 0.1, 0.1]}, "unsupported_box_geometry"),
        ({"target": [float("nan"), 0]}, "nonfinite_input"),
        ({"target": [4]}, "invalid_shape"),
        ({"box_yaw": math.pi / 2}, "unsupported_box_face"),
    ],
)
def test_rejected_preconditions(change, reason):
    args = inputs() | change
    assert preflight(**args) == reason
    with pytest.raises(ValueError, match=reason):
        PushSession(object_id="box", **args)


def test_request_and_observations_are_not_mutated():
    args = inputs()
    skill = PushSession(object_id="box", **args)
    palms = {"left": np.array([3.4, 0.2, 0.7]), "right": np.array([3.4, -0.2, 0.7])}
    before = args["base"].copy(), args["box"].copy()
    for t in [0, 2, 5, 13, 16]:
        goals, cmd = skill.command(t, args["base"], 0, args["box"], palms)
        assert np.isfinite(cmd).all()
        assert all(np.isfinite(v).all() for v in goals.values())
    assert np.array_equal(before[0], args["base"])
    assert np.array_equal(before[1], args["box"])
    assert not skill.result(args["box"])["success"]


def test_world_rotation_equivariance():
    args = inputs()
    a = PushSession(object_id="box", **args)
    rot = np.array([[0.0, -1, 0], [1.0, 0, 0], [0.0, 0, 1]])
    rotated = args | {
        "base": rot @ args["base"],
        "box": rot @ args["box"],
        "yaw": math.pi / 2,
        "box_yaw": math.pi / 2,
        "target": (rot @ [*args["target"], 0])[:2],
    }
    b = PushSession(object_id="box", **rotated)
    palms = {"left": np.array([3.4, 0.2, 0.7]), "right": np.array([3.4, -0.2, 0.7])}
    ga, ca = a.command(3, args["base"], 0, args["box"], palms)
    gb, cb = b.command(
        3, rotated["base"], math.pi / 2, rotated["box"], {k: rot @ v for k, v in palms.items()}
    )
    assert np.allclose(ca, cb)
    assert all(np.allclose(rot @ ga[k], gb[k]) for k in ga)


def test_success_requires_contact_release_target_and_valid_physics():
    s = PushSession(object_id="box", **inputs())
    s.elapsed = 18
    box = [4.08, 0, 0.35]
    assert not s.result(box)["success"]
    s.control.push_contact_seconds = 1
    s.control.release_seconds = 0.6
    assert s.result(box)["success"]
    assert not s.result(box, valid=False)["success"]
    assert not s.result(box, reason="FALLEN")["success"]
    assert not s.result([4, 0, 0.35])["success"]
    s.peak_force = 121
    assert not s.result(box)["success"]
