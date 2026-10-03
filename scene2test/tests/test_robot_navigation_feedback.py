"""CPU geometry/ideal kinematics only: these tests are not G1 gait evidence."""

import json
import math
from types import SimpleNamespace

import numpy as np
import pytest

from robot_vlm.execution_feedback import MotionFeedback, policy_feedback
from robot_vlm.goal_policy import GoalAction
from robot_vlm.navigation_tools import PathFollower, follow_command, segment_clear
from robot_vlm.push_policy import PushEnvelope
from robot_vlm.wire_contract import GoalEnvelope


def observation(rects=()):
    geometry = [
        SimpleNamespace(
            object_id="clear_floor",
            center_m=[0, 0, 0],
            size_m=[20, 20, 0.1],
            rotation_matrix=np.eye(3).ravel(),
        )
    ]
    for i, (a, b, c, d) in enumerate(rects):
        geometry.append(
            SimpleNamespace(
                object_id=f"block_{i}",
                center_m=[(a + b) / 2, (c + d) / 2, 0.5],
                size_m=[b - a, d - c, 1],
                rotation_matrix=np.eye(3).ravel(),
            )
        )
    return SimpleNamespace(geometry=geometry)


@pytest.mark.parametrize(
    "start,end,rects,clear",
    [
        ([0, 0], [1, 0], [], True),
        ([0, 0], [1, 0], [[0.499, 0.501, -0.01, 0.01]], False),
        ([0, 0], [0, 0], [[-0.1, 0.1, -0.1, 0.1]], False),
        ([0, 0], [0, 0], [[1, 2, 1, 2]], True),
        ([0, 0], [1, 0], [[0.4, 0.6, 0.39, 0.5]], False),
        ([0, 0], [1, 0], [[0.4, 0.6, 0.41, 0.5]], True),
        ([0, 0], [2, 2], [[1, 1.01, 1, 1.01]], False),
        ([9.7, 0], [8, 0], [], False),
        ([0, 0], [float("nan"), 0], [], False),
    ],
)
def test_continuous_segment_clearance(start, end, rects, clear):
    assert segment_clear(start, end, [-10, 10, -10, 10], rects) == clear


def test_clear_segments_agree_with_dense_independent_point_distance_check():
    rng = np.random.default_rng(17)
    rect = [-0.1, 0.3, -0.2, 0.2]
    checked = 0
    for _ in range(200):
        start, end = rng.uniform(-2, 2, (2, 2))
        if segment_clear(start, end, [-10, 10, -10, 10], [rect]):
            points = start + np.linspace(0, 1, 1001)[:, None] * (end - start)
            dx = np.maximum(np.maximum(rect[0] - points[:, 0], points[:, 0] - rect[1]), 0)
            dy = np.maximum(np.maximum(rect[2] - points[:, 1], points[:, 1] - rect[3]), 0)
            assert np.min(dx * dx + dy * dy) > 0.4**2
            checked += 1
    assert checked > 50


def integrate(command, base, heading, dt=0.01):
    vx, vy, w = command
    base[0] += dt * (math.cos(heading) * vx - math.sin(heading) * vy)
    base[1] += dt * (math.sin(heading) * vx + math.cos(heading) * vy)
    return heading + dt * w


@pytest.mark.parametrize("offset", [0.15, 0.2])
def test_close_waypoint_orbit_reproduction_and_local_fix(offset):
    old_path = [[i * 0.05, 0] for i in range(21)]
    base, heading = [0, offset, 0], 0.0
    for _ in range(1000):
        heading = integrate(follow_command(base, heading, old_path), base, heading)
    assert math.dist(base[:2], [1, 0]) > 0.8  # reproduced old local trap

    route = [[i * 0.05, 0] for i in range(21)]
    original = [p[:] for p in route]
    follower = PathFollower(route, observation(), [1, 0])
    base, heading = [0, offset, 0], 0.0
    for _ in range(1000):
        cmd = follower.command(base, heading)
        assert 0 <= cmd[0] <= 0.2 and abs(cmd[1]) <= 0.15 and abs(cmd[2]) <= 0.4
        heading = integrate(cmd, base, heading)
        if math.dist(base[:2], [1, 0]) < 0.12:
            break
    assert math.dist(base[:2], [1, 0]) < 0.12
    assert route == original


def test_lookahead_does_not_cut_through_obstacle_corner():
    rects = [[0.2, 0.5, 0.2, 0.5]]
    # A locally bent path around the inflated lower-left corner.
    path = [[0, -0.25], [0.15, -0.25], [0.35, -0.25], [0.55, -0.25], [0.95, -0.25], [0.95, 0.25]]
    follower = PathFollower(path, observation(rects), path[-1])
    base = [-0.25, 0.15, 0]
    cmd = follower.command(base, 0)
    assert follower.last["lookahead_xy_m"] != path[-1]
    if follower.last["lookahead_xy_m"] is not None:
        assert segment_clear(base, follower.last["lookahead_xy_m"], follower.floor, rects)
        # The velocity vector points along the clear connector even at lateral saturation.
        dx = follower.last["lookahead_xy_m"][0] - base[0]
        dy = follower.last["lookahead_xy_m"][1] - base[1]
        assert cmd[0] * dy - cmd[1] * dx == pytest.approx(0)


def test_blocked_current_pose_stops_and_reports_no_teleport_or_route_rewrite():
    f = PathFollower([[0, 0], [0.05, 0]], observation([[-0.1, 0.1, -0.1, 0.1]]), [0.05, 0])
    assert f.command([0, 0, 0.7], 0) == [0, 0, 0]
    assert f.last["status"] == "blocked_connector"


def test_behind_target_turns_without_forward_or_lateral_motion():
    f = PathFollower([[1, 0]], observation(), [1, 0])
    command = f.command([0, 0, 0.7], math.pi)
    assert command[:2] == [0, 0]
    assert abs(command[2]) == 0.4


def test_path_progress_is_local_not_global_nearest_branch():
    path = [[i * 0.05, 0] for i in range(41)] + [[2, 1], [0, 1], [0, 0.01]]
    f = PathFollower(path, observation(), path[-1])
    f.command([0, 0.01, 0.7], 0)
    assert f.last["path_index"] == 0
    assert f.last["lookahead_index"] < 10


def move(**kwargs):
    return GoalAction(
        state_version=0,
        plan_summary="move sideways",
        action="move",
        target_xy_m=None,
        skill_request=None,
        vx_mps=0.0,
        vy_mps=0.0,
        yaw_rate_rps=0.0,
        duration_s=1.0,
    ).model_copy(update=kwargs)


def test_motion_feedback_counts_zero_commands_despite_drift_and_no_inferred_intent():
    a = move()
    m = MotionFeedback(a, 20, [1, 2, 0.74], -math.pi / 2, [7, 0])
    m.observe([1.02, 2, 0.74], [0, 0, 0])
    result = m.result(21, [1.02, 2, 0.74], -math.pi / 2)
    assert result["commanded_stationary"] is True
    assert result["elapsed_s"] == 1
    assert result["net_translation_m"] == pytest.approx(0.02)
    assert result["delta_start_body_xy_m"] == pytest.approx([0, 0.02])
    memory = [{"action": a.model_dump(), "execution": {"motion": result}} for _ in range(5)]
    feedback = policy_feedback(memory, -math.pi / 2)
    assert feedback["recent_consecutive_zero_move_commands"] == 5
    assert feedback["body_left_world_xy"] == pytest.approx([1, 0])
    assert a.vy_mps == 0  # no rewrite from prose, no retry or extra call
    memory.append({"action": a.model_dump(), "execution": {"status": "stale_rejected"}})
    assert policy_feedback(memory, 0)["recent_consecutive_zero_move_commands"] == 0
    assert policy_feedback([], 0)["last_motion"] is None


@pytest.mark.parametrize("envelope", [GoalEnvelope, PushEnvelope])
@pytest.mark.parametrize("vy", [0.0, 0.1, -0.1])
def test_actual_wire_schema_preserves_zero_and_nonzero_numeric_moves(envelope, vy):
    value = {"command": move(vy_mps=vy).model_dump()}
    command = envelope.model_validate_json(json.dumps(value)).command
    assert command.vy_mps == vy
    assert command.plan_summary == "move sideways"


def test_empty_execution_has_unknown_command_mean_not_fake_zero():
    m = MotionFeedback(move(), 20, [1, 2, 0.74], 0, [7, 0])
    result = m.result(20, [1, 2, 0.74], 0)
    assert result["samples"] == 0 and result["mean_command_body"] is None
