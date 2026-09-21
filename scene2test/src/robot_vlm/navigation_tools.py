"""Robot-internal conservative planner and pose hold; never an evaluator route."""

import math
from collections import deque

import numpy as np

RADIUS = 0.40
RESOLUTION = 0.05


def rectangles(observation):
    result = []
    floor = None
    for geom in observation.geometry:
        half = np.abs(np.array(geom.rotation_matrix).reshape(3, 3)) @ (np.array(geom.size_m) / 2)
        xy = np.array(geom.center_m[:2])
        bounds = [xy[0] - half[0], xy[0] + half[0], xy[1] - half[1], xy[1] + half[1]]
        if geom.object_id == "clear_floor":
            floor = bounds
        else:
            result.append(bounds)
    if floor is None:
        raise ValueError("support floor missing")
    return floor, result


def plan(observation, target):
    target = np.asarray(target, dtype=float)
    if target.shape != (2,) or not np.isfinite(target).all():
        raise ValueError("finite 2D target required")
    floor, rects = rectangles(observation)
    x0, x1, y0, y1 = floor
    nx, ny = int((x1 - x0) / RESOLUTION), int((y1 - y0) / RESOLUTION)
    if nx * ny > 50000 or nx < 1 or ny < 1:
        raise ValueError("unsupported map size")
    xx, yy = np.meshgrid(
        x0 + (np.arange(nx) + 0.5) * RESOLUTION, y0 + (np.arange(ny) + 0.5) * RESOLUTION
    )
    blocked = (xx < x0 + RADIUS) | (xx > x1 - RADIUS) | (yy < y0 + RADIUS) | (yy > y1 - RADIUS)
    for a, b, c, d in rects:
        dx = np.maximum(np.maximum(a - xx, xx - b), 0)
        dy = np.maximum(np.maximum(c - yy, yy - d), 0)
        blocked |= dx * dx + dy * dy <= RADIUS**2

    def cell(xy):
        return math.floor((xy[1] - y0) / RESOLUTION), math.floor((xy[0] - x0) / RESOLUTION)

    def free(p):
        return 0 <= p[0] < ny and 0 <= p[1] < nx and not blocked[p]

    start, goal = cell(observation.base_xyz_m[:2]), cell(target)
    if not free(start) or not free(goal):
        return {"status": "blocked_endpoint", "path_xy_m": []}
    parents, queue = {start: None}, deque([start])
    while queue:
        a = queue.popleft()
        if a == goal:
            break
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            b = a[0] + dy, a[1] + dx
            if free(b) and b not in parents:
                parents[b] = a
                queue.append(b)
    path, node = [], goal if goal in parents else None
    while node is not None:
        path.append([float(xx[node]), float(yy[node])])
        node = parents[node]
    return {
        "status": "path_found" if path else "no_path",
        "path_xy_m": path[::-1],
        "radius_m": RADIUS,
        "resolution_m": RESOLUTION,
        "claim": "static circular-footprint route, not whole-body feasibility",
    }


def hold_command(base, heading, anchor, anchor_heading):
    delta = np.asarray(anchor[:2]) - np.asarray(base[:2])
    c, s = math.cos(heading), math.sin(heading)
    body = np.array([c * delta[0] + s * delta[1], -s * delta[0] + c * delta[1]])
    error = math.atan2(math.sin(anchor_heading - heading), math.cos(anchor_heading - heading))
    return [*np.clip(body * 0.8, -0.12, 0.12).tolist(), float(np.clip(error, -0.3, 0.3))]


def follow_command(base, heading, path):
    while len(path) > 1 and math.dist(base[:2], path[0]) < 0.08:
        path.pop(0)
    dx, dy = np.asarray(path[0]) - np.asarray(base[:2])
    error = math.atan2(
        math.sin(math.atan2(dy, dx) - heading), math.cos(math.atan2(dy, dx) - heading)
    )
    return [0.20 * max(0, math.cos(error)), 0.0, float(np.clip(error, -0.4, 0.4))]
