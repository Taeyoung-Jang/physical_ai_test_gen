"""Known-map/ground-truth-pose baseline. No LLM, perception or learned navigation."""

from __future__ import annotations

import math

import numpy as np

VERSION = "gt-waypoint-v2"


def segment_free(a, b, nav, terrain_spec=None):
    a, b = np.asarray(a), np.asarray(b)
    resolution = nav["resolution_m"]
    for t in np.linspace(0, 1, max(2, math.ceil(np.linalg.norm(b - a) / (resolution / 4)) + 1)):
        x, y = np.floor((a * (1 - t) + b * t) / resolution).astype(int)
        if not (0 <= x < nav["width"] and 0 <= y < nav["height"]) or nav["blocked"][y][x]:
            return False
    if terrain_spec is not None:
        from procedural_world.terrain import segment_traversable

        return segment_traversable(terrain_spec, a, b)
    return True


def simplify_path(nav, terrain_spec=None):
    points = nav["path_xy_m"]
    if not points:
        raise ValueError("no navigation path")
    result, index = [points[0]], 0
    while index < len(points) - 1:
        next_index = index + 1
        for j in range(len(points) - 1, index, -1):
            if segment_free(points[index], points[j], nav, terrain_spec):
                next_index = j
                break
        result.append(points[next_index])
        index = next_index
    return np.asarray(result)


class Follower:
    def __init__(self, nav, speed=0.3, tolerance=0.25, boxes=None, terrain_spec=None):
        self.nav = nav
        self.boxes = boxes
        self.terrain_spec = terrain_spec
        self.path = simplify_path(nav, terrain_spec)
        self.index = 1
        self.speed = speed
        self.tolerance = tolerance
        self.reached = False

    def command(self, xy, yaw):
        xy = np.asarray(xy)
        if np.linalg.norm(xy - self.path[-1]) <= self.tolerance:
            self.reached = True
            return np.zeros(3)
        while self.index < len(self.path) - 1 and np.linalg.norm(xy - self.path[self.index]) < 0.15:
            self.index += 1
        endpoint = self.path[self.index]
        start = self.path[self.index - 1]
        segment = endpoint - start
        length = np.linalg.norm(segment)
        progress = np.clip(np.dot(xy - start, segment) / max(length, 1e-9), 0.0, length)
        target = start + segment / max(length, 1e-9) * min(length, progress + 0.65)
        delta = target - xy
        heading = math.atan2(delta[1], delta[0])
        error = math.atan2(math.sin(heading - yaw), math.cos(heading - yaw))
        forward = min(self.speed, 0.7 * np.linalg.norm(delta)) * max(0.0, math.cos(error))
        if abs(error) > 0.5:
            forward = 0.0
        command = np.array([forward, 0.0, np.clip(1.6 * error, -0.5, 0.5)])
        # Short-horizon static collision guard. Rotation itself is not a whole-body guarantee.
        projected = xy + 0.6 * forward * np.array([math.cos(yaw), math.sin(yaw)])
        if not self.motion_free(xy, projected):
            command[0] = 0.0
        return command

    def motion_free(self, a, b):
        if self.terrain_spec is not None:
            from procedural_world.terrain import segment_traversable

            if not segment_traversable(self.terrain_spec, a, b):
                return False
        if self.boxes is None:
            return segment_free(a, b, self.nav)
        points = np.linspace(a, b, max(2, math.ceil(np.linalg.norm(b - a) / 0.02) + 1))
        clearance = self.nav["robot_radius_m"] + self.nav["safety_margin_m"] + 0.01
        for box in self.boxes:
            delta = np.maximum(
                np.abs(points - np.array(box.position[:2])) - np.array(box.size[:2]) / 2, 0.0
            )
            if np.any(np.linalg.norm(delta, axis=1) <= clearance):
                return False
        return True
