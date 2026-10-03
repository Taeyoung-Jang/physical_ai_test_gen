"""Geometry/ideal-motion regressions, NOT GPU gait or paid model validation."""

import math
from types import SimpleNamespace

import numpy as np
import pytest

from robot_vlm import navigation_tools as nav


def observation(base, rects=(), floor=(-5, 5, -5, 5)):
    geometry = []
    for name, (a, b, c, d) in [("clear_floor", floor), *[(str(i), r) for i, r in enumerate(rects)]]:
        geometry.append(
            SimpleNamespace(
                object_id=name,
                center_m=[(a + b) / 2, (c + d) / 2, 0],
                size_m=[b - a, d - c, 0.1],
                rotation_matrix=np.eye(3).ravel(),
            )
        )
    return SimpleNamespace(base_xyz_m=[*base[:2], 0.74], geometry=geometry)


# Rounded public simulation geometry from the reviewed live archive (three
# first-blocked samples), embedded so tests need no external archive/assets.
LIVE_RECTS = [
    [0, 8, -2.1, -2],
    [0, 8, 2, 2.1],
    [-0.1, 0, -2.1, 2.1],
    [8, 8.1, -2.1, 2.1],
    [2.44198994, 2.84414002, -1.77910920, -1.41113992],
    [5.10883405, 5.52206879, 1.63914849, 1.95],
    [3.6, 4.4, -0.80093354, 0.29906646],
]
LIVE_FLOOR = [-0.2, 8.2, -2.2, 2.2]


@pytest.mark.parametrize("base", [[3.550750, 0.693637], [4.329533, 0.698865], [4.707281, 0.548407]])
@pytest.mark.parametrize("heading", [0.0, math.pi / 2, math.pi])
def test_saved_blocked_poses_escape_and_replan_in_ideal_motion(base, heading):
    obs = observation(base, LIVE_RECTS, LIVE_FLOOR)
    initial = nav.plan(obs, [7, 0])
    assert initial["status"] == "blocked_endpoint"
    floor, rects = nav.rectangles(obs)
    assert not nav.segment_clear(base, [base[0], base[1] + 0.2], floor, rects)
    session = nav.NavigationSession(obs, [7, 0], initial)
    assert session.can_execute
    previous = nav.clearances(base, floor, rects)
    for i in range(301):
        command = session.command(obs.base_xyz_m, heading, i * 0.01, lambda: obs)
        assert command is not None, session.audit(i * 0.01)
        if session.replans:
            break
        assert session.last["status"] == "clearance_recovery"
        assert math.hypot(*command[:2]) <= 0.100000001 and command[2] == 0
        vx, vy = command[:2]
        obs.base_xyz_m[0] += 0.01 * (math.cos(heading) * vx - math.sin(heading) * vy)
        obs.base_xyz_m[1] += 0.01 * (math.sin(heading) * vx + math.cos(heading) * vy)
        now = nav.clearances(obs.base_xyz_m, floor, rects)
        for a, b in zip(previous, now, strict=True):
            assert b >= min(a, 0.4) - 1e-9  # no new margin infringement
        previous = now
    assert i * 0.01 < 3 and session.replans == 1 and session.recoveries == 1
    assert min(previous) >= 0.515
    assert session.target == [7, 0]
    assert [e["event"] for e in session.events] == [
        "blocked_connector",
        "recovery_started",
        "recovery_completed",
        "replan",
    ]


def test_plan_has_padding_and_safe_exact_endpoint_connectors():
    obs = observation([1, 0], LIVE_RECTS, LIVE_FLOOR)
    result = nav.plan(obs, [7, 0])
    path = result["path_xy_m"]
    assert result["status"] == "path_found"
    assert result["radius_m"] == 0.4 and result["planning_radius_m"] == 0.5
    assert path[0] == [1, 0] and path[-1] == [7, 0]
    for a, b in zip(path, path[1:]):
        assert nav.segment_clear(a, b, LIVE_FLOOR, LIVE_RECTS, radius=0.5)
    # Exact hard-clear endpoint inside added margin stays the requested target.
    obs = observation([-1, 0], [[0, 1, -0.5, 0.5]])
    target = [-0.42, 0]
    result = nav.plan(obs, target)
    assert result["status"] == "path_found" and result["path_xy_m"][-1] == target
    f, r = nav.rectangles(obs)
    assert all(
        nav.tracking_segment_clear(a, b, f, r)
        for a, b in zip(result["path_xy_m"], result["path_xy_m"][1:])
    )


def test_no_silent_radius_reduction_for_narrow_route():
    obs = observation([-1, 0], floor=[-2, 4, -0.48, 0.48])
    assert nav.segment_clear([-1, 0], [3, 0], [-2, 4, -0.48, 0.48], [])
    result = nav.plan(obs, [3, 0])
    assert result["status"] == "no_tracking_clearance" and not result["path_xy_m"]
    assert not nav.NavigationSession(obs, [3, 0], result).can_execute


@pytest.mark.parametrize("base", [[0, 0], [0, 0.2], [0, 0.539]])
def test_deep_or_actual_geometric_overlap_is_never_auto_escaped(base):
    obs = observation(base, [[-0.2, 0.2, -0.2, 0.2]])
    floor, rects = nav.rectangles(obs)
    assert nav.recovery_target(base, [2, 0], floor, rects) is None
    s = nav.NavigationSession(obs, [2, 0], nav.plan(obs, [2, 0]))
    assert not s.can_execute


def shallow_session():
    obs = observation([0, 0.595], [[-0.2, 0.2, -0.2, 0.2]])
    return obs, nav.NavigationSession(obs, [2, 0], nav.plan(obs, [2, 0]))


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("still", "recovery_no_progress"),
        ("worse", "recovery_clearance_worsened"),
        ("distance", "recovery_distance_limit"),
        ("timeout", "recovery_timeout"),
        ("geometry", "recovery_clearance_worsened"),
    ],
)
def test_recovery_returns_early_on_observed_guard_without_goal_verdict(fault, reason):
    obs, session = shallow_session()
    assert session.command(obs.base_xyz_m, 0, 0, lambda: obs) is not None
    time_s = 0.1
    if fault == "still":
        time_s = 1.01
    elif fault == "worse":
        obs.base_xyz_m[1] -= 0.025
    elif fault == "distance":
        obs.base_xyz_m[1] += 0.4
    elif fault == "geometry":
        obs.geometry[1].center_m[1] += 0.1
    elif fault == "timeout":
        # Slow but non-stagnant ideal progress; still cannot exceed three seconds.
        for i in range(1, 30):
            obs.base_xyz_m[1] += 0.001
            assert session.command(obs.base_xyz_m, 0, i * 0.1, lambda: obs) is not None
        time_s = 3.0
    assert session.command(obs.base_xyz_m, 0, time_s, lambda: obs) is None
    assert session.stop_reason == reason
    assert session.command(obs.base_xyz_m, 0, 10, lambda: obs) is None
    assert session.audit(time_s)["status"] == reason
    assert "task_outcome" not in session.audit(time_s)


def test_outward_escape_cannot_move_toward_another_violated_margin():
    floor = [-2, 2, -2, 2]
    rects = [[-0.2, 0.2, -0.2, 0.2], [0.58, 0.8, 0.3, 0.8]]
    start = [0, 0.595]
    assert not nav.escape_segment_clear(start, [0.2, 0.8], floor, rects)
    assert not nav.escape_segment_clear(start, [0, 0.9], floor, [[-0.2, 0.2, 0.85, 1]])
    # Correct escape math also handles conservative floor-edge infringement.
    assert nav.escape_segment_clear([-1.605, 0], [-1.455, 0], floor, [])
    assert not nav.escape_segment_clear([float("nan"), 0], [0, 0], floor, [])


def test_replans_are_bounded_and_cannot_resend_policy_calls(monkeypatch):
    obs = observation([0, 0])
    s = nav.NavigationSession(obs, [1, 0], nav.plan(obs, [1, 0]))

    def blocked(self, base, heading):
        self.last = {"status": "blocked_connector"}
        return [0, 0, 0]

    monkeypatch.setattr(nav.PathFollower, "command", blocked)
    assert s.command(obs.base_xyz_m, 0, 0, lambda: obs) is None
    assert s.stop_reason == "blocked_after_replan" and s.replans == 1
    # Exhausted replan allowance returns immediately, without a new attempt.
    s = nav.NavigationSession(obs, [1, 0], nav.plan(obs, [1, 0]))
    s.replans = nav.MAX_REPLANS
    assert s.command(obs.base_xyz_m, 0, 0, lambda: obs) is None
    assert s.stop_reason == "replan_limit" and s.replans == nav.MAX_REPLANS
