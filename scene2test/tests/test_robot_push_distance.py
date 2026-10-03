"""CPU-only distance gates, including the reviewed .25 goal-region rejection.

These checks do not establish alignment convergence, physical pushing or goal success.
"""

import math

import numpy as np
import pytest

from robot_vlm.push_alignment import readiness
from robot_vlm.push_skill import PushSession, preflight, supported_push_distance


def aligned_inputs(distance, *, x=7.0, yaw=0.0):
    direction = np.array([math.cos(yaw), math.sin(yaw)])
    box = np.array([x, 0.35, 0.35])
    return dict(
        base=np.r_[box[:2] - 0.82 * direction, 0.74],
        yaw=yaw,
        box=box,
        box_yaw=yaw,
        size=[0.8, 1.1, 0.7],
        target=box[:2] + distance * direction,
    )


@pytest.mark.parametrize("distance", [0.075, 0.20])
@pytest.mark.parametrize("x", [0.0, 4.0, 7.0])
@pytest.mark.parametrize("yaw", [0.0, 0.7, -math.pi / 2])
def test_inclusive_endpoints_after_translation_and_rotation(distance, x, yaw):
    args = aligned_inputs(distance, x=x, yaw=yaw)
    before = args["target"].copy(), args["box"].copy()
    assert preflight(**args) is None
    state = readiness(**args)
    assert state["checks"]["distance"] and state["ready"] and state["correctable"]
    session = PushSession(object_id="clear_box_geom", **args)
    # Do not silently clamp the LLM target or falsify the measured displacement.
    assert session.distance == state["measured"]["push_distance_m"]
    assert np.array_equal(session.target, before[0])
    assert np.array_equal(args["target"], before[0])
    assert np.array_equal(args["box"], before[1])


@pytest.mark.parametrize("distance", [0.075 - 5e-10, 0.20 + 5e-10])
def test_only_absolute_nanometre_roundoff_is_tolerated(distance):
    args = aligned_inputs(distance, x=0.0)
    assert preflight(**args) is None
    state = readiness(**args)
    assert state["ready"] and state["correctable"]
    assert state["limits"]["push_distance_m"] == [0.075, 0.20]
    assert state["limits"]["push_distance_abs_tolerance_m"] == 1e-9
    assert state["measured"]["push_distance_m"] == distance


@pytest.mark.parametrize(
    "distance", [0.075 - 2e-9, 0.20 + 2e-9, 0.075 - 1e-6, 0.20 + 1e-6, 0.0, 1.0]
)
def test_real_range_violations_still_rejected_by_both_gates(distance):
    args = aligned_inputs(distance, x=0.0)
    assert preflight(**args) == "unsupported_push_distance"
    state = readiness(**args)
    assert not state["checks"]["distance"]
    assert not state["ready"] and not state["correctable"]
    with pytest.raises(ValueError, match="unsupported_push_distance"):
        PushSession(object_id="clear_box_geom", **args)


@pytest.mark.parametrize("distance", [float("nan"), float("inf"), -float("inf"), -0.2])
def test_shared_distance_gate_rejects_nonfinite_and_negative_values(distance):
    assert not supported_push_distance(distance)


def test_reviewed_twenty_cm_request_can_enter_alignment_not_skip_it():
    # attempt_00002/skill_007.json: measured gate inputs, not an archive rewrite.
    heading = -8.25652649027569e-08
    args = dict(
        base=[6.153471360107413, 0.24144755948960073, 0.7423651993718158],
        yaw=heading - (-0.08490959563113085),
        box=[6.999999999999894, 0.35000001651305296, 0.34994286659620844],
        box_yaw=heading - (-8.256527060811e-08),
        size=[0.8, 1.1, 0.7],
        target=[7.2, 0.35],
    )
    state = readiness(**args)
    assert state["measured"]["push_distance_m"] > 0.2
    assert state["checks"]["distance"]
    assert not state["checks"]["lateral"] and not state["ready"]
    assert state["correctable"]
    assert preflight(**args) == "near_aligned_approach_required"
    with pytest.raises(ValueError, match="near_aligned_approach_required"):
        PushSession(object_id="clear_box_geom", **args)


def test_reviewed_fifteen_cm_request_still_outside_alignment_entry():
    # Reconstructed from attempt_00002/skill_009.json's measured heading and pose.
    # Its 14.54cm lateral error is not roundoff.
    heading = -1.2803431537191417e-07
    args = dict(
        base=[6.170853034105525, 0.20461324115751353, 0.7436016641178866],
        yaw=heading - (-0.04071819622564338),
        box=[6.999999999999894, 0.35000001920514734, 0.34994286659620855],
        box_yaw=heading - (-1.280343229262757e-07),
        size=[0.8, 1.1, 0.7],
        target=[7.15, 0.35],
    )
    state = readiness(**args)
    assert state["checks"]["distance"]
    assert state["measured"]["lateral_error_m"] > 0.14
    assert not state["ready"] and not state["correctable"]
    assert state["limits"]["lateral_error_abs_m"] == 0.06
    assert preflight(**args) == "near_aligned_approach_required"
