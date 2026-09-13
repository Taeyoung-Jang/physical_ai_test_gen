import numpy as np

from procedural_world.core import navigation_map
from procedural_world.navigation_stages import stage_world
from simulation_server.navigation import Follower, segment_free


def test_geometry_guard_does_not_trap_safe_pose_in_padded_raster_cell():
    spec = stage_world("obstacle")
    nav = navigation_map(spec)
    follower = Follower(nav, boxes=spec.boxes)
    xy = np.array([7.30, 9.18])  # Observed v1 timeout location, outside actual obstacle footprint.
    assert not segment_free(xy, xy, nav)
    assert follower.motion_free(xy, np.array([7.4, 9.3]))
    assert not follower.motion_free(xy, np.array([8.1, 8.1]))


def test_lookahead_corrects_cross_track_before_distant_waypoint():
    spec = stage_world("obstacle")
    follower = Follower(navigation_map(spec), boxes=spec.boxes)
    follower.index = 2
    command = follower.command([9.5, 9.0], 0.0)
    assert command[0] > 0
    assert command[2] > 0  # Correct toward reference segment above the robot.
    assert command[0] <= 0.3 and abs(command[2]) <= 0.5
