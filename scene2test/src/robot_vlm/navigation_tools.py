"""Robot-internal conservative planner and pose hold; never an evaluator route."""

import math
from collections import deque

import numpy as np

RADIUS = 0.40
RESOLUTION = 0.05
FOLLOWER_VERSION = "clearance-recovery-v3"
LOOKAHEAD_M = 0.35
TRACKING_MARGIN = 0.10
PLANNING_RADIUS = RADIUS + TRACKING_MARGIN
CONNECTOR_LIMIT = 0.35
RECOVERY_MAX_INTRUSION = 0.06
RECOVERY_MAX_SECONDS = 3.0
RECOVERY_SPEED = 0.10
MAX_REPLANS = 2


def follower_contract():
    return {
        "version": FOLLOWER_VERSION,
        "lookahead_m": LOOKAHEAD_M,
        "radius_m": RADIUS,
        "planning_radius_m": PLANNING_RADIUS,
        "tracking_margin_m": TRACKING_MARGIN,
        "max_forward_mps": 0.20,
        "max_lateral_mps": 0.15,
        "max_yaw_rate_rps": 0.40,
        "geometry": "GT snapshot refreshed on blockage/recovery/replan; not full-body safety",
        "endpoint_connectors": "up to 0.35m at original 0.40m radius; no narrow-route fallback",
        "blocked_connector": "bounded recovery/replan or early tool return; not a goal verdict",
        "recovery": {
            "max_intrusion_m": RECOVERY_MAX_INTRUSION,
            "max_distance_m": CONNECTOR_LIMIT,
            "max_seconds_each": RECOVERY_MAX_SECONDS,
            "speed_mps": RECOVERY_SPEED,
            "max_replans_per_action": MAX_REPLANS,
            "no_progress_seconds": 1.0,
            "worsening_tolerance_m": 0.02,
            "budget": "inside original action deadline; no extra policy call or grace",
        },
    }


def segment_clear(start, end, floor, rects, *, radius=RADIUS):
    """Continuous conservative clearance against world AABBs, including endpoints.

    The minimum segment/rectangle distance occurs at an endpoint, a corner's
    projection, or an intersection. No sparse sampling through thin obstacles.
    """
    a, b = tuple(map(float, start[:2])), tuple(map(float, end[:2]))
    if not all(map(math.isfinite, (*a, *b))):
        return False
    x0, x1, y0, y1 = floor
    if any(
        not (x0 + radius <= p[0] <= x1 - radius and y0 + radius <= p[1] <= y1 - radius)
        for p in (a, b)
    ):
        return False
    delta = (b[0] - a[0], b[1] - a[1])
    length_sq = delta[0] ** 2 + delta[1] ** 2
    for left, right, bottom, top in rects:
        lo, hi = (left, bottom), (right, top)
        enter, leave = 0.0, 1.0
        for axis in (0, 1):
            if abs(delta[axis]) < 1e-12:
                if not lo[axis] <= a[axis] <= hi[axis]:
                    enter, leave = 1.0, 0.0
                    break
            else:
                t0, t1 = sorted(
                    ((lo[axis] - a[axis]) / delta[axis], (hi[axis] - a[axis]) / delta[axis])
                )
                enter, leave = max(enter, t0), min(leave, t1)
        if enter <= leave:
            return False
        distances = [
            max(left - p[0], 0, p[0] - right) ** 2 + max(bottom - p[1], 0, p[1] - top) ** 2
            for p in (a, b)
        ]
        for corner in ([left, bottom], [left, top], [right, bottom], [right, top]):
            projection = (corner[0] - a[0]) * delta[0] + (corner[1] - a[1]) * delta[1]
            t = max(0.0, min(1.0, projection / length_sq)) if length_sq else 0.0
            distances.append(
                (corner[0] - a[0] - t * delta[0]) ** 2 + (corner[1] - a[1] - t * delta[1]) ** 2
            )
        if min(distances) <= radius**2:
            return False
    return True


def _rect_distance(point, rect):
    a, b, c, d = rect
    return math.hypot(max(a - point[0], 0, point[0] - b), max(c - point[1], 0, point[1] - d))


def clearances(point, floor, rects):
    """One surface distance per floor edge/obstacle, not full-body clearance."""
    x, y = point[:2]
    a, b, c, d = floor
    return [x - a, b - x, y - c, d - y, *(_rect_distance(point, r) for r in rects)]


def tracking_segment_clear(start, end, floor, rects):
    # Preserve the extra margin through corners. Exact endpoint connectors and
    # off-route poses may start/end inside the extra margin, never inside RADIUS.
    if not segment_clear(start, end, floor, rects):
        return False
    # Floor is convex: endpoint checks already bound the entire connector.
    # Check each obstacle independently of unrelated floor-edge proximity.
    return all(
        segment_clear(
            start,
            end,
            [-math.inf, math.inf, -math.inf, math.inf],
            [rect],
            radius=min(PLANNING_RADIUS, _rect_distance(start, rect), _rect_distance(end, rect))
            - 1e-8,
        )
        for rect in rects
    )


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
    # Inflate by half a cell diagonal too: every point in an accepted cell,
    # hence every 4-neighbour grid edge, retains the requested planning margin.
    grid_radius = PLANNING_RADIUS + RESOLUTION / math.sqrt(2)
    blocked = (
        (xx < x0 + grid_radius)
        | (xx > x1 - grid_radius)
        | (yy < y0 + grid_radius)
        | (yy > y1 - grid_radius)
    )
    for a, b, c, d in rects:
        dx = np.maximum(np.maximum(a - xx, xx - b), 0)
        dy = np.maximum(np.maximum(c - yy, yy - d), 0)
        blocked |= dx * dx + dy * dy <= grid_radius**2

    def free(p):
        return 0 <= p[0] < ny and 0 <= p[1] < nx and not blocked[p]

    metadata = {
        "radius_m": RADIUS,
        "planning_radius_m": PLANNING_RADIUS,
        "resolution_m": RESOLUTION,
        "endpoint_connector_limit_m": CONNECTOR_LIMIT,
        "claim": "padded static circular-footprint route, not whole-body feasibility",
    }
    endpoints = [observation.base_xyz_m[:2], target]
    if not all(segment_clear(p, p, floor, rects) for p in endpoints):
        return {"status": "blocked_endpoint", "path_xy_m": [], **metadata}

    def connector(xy):
        distance = (xx - xy[0]) ** 2 + (yy - xy[1]) ** 2
        candidates = np.argwhere((distance <= CONNECTOR_LIMIT**2) & ~blocked)
        for row in sorted(map(tuple, candidates), key=lambda p: distance[p]):
            if tracking_segment_clear(xy, [xx[row], yy[row]], floor, rects):
                return row
        return None

    start, goal = (connector(p) for p in endpoints)
    if start is None or goal is None:
        return {"status": "no_tracking_clearance", "path_xy_m": [], **metadata}
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
        "path_xy_m": [list(endpoints[0]), *path[::-1], target.tolist()] if path else [],
        **metadata,
    }


def hold_command(base, heading, anchor, anchor_heading):
    delta = np.asarray(anchor[:2]) - np.asarray(base[:2])
    c, s = math.cos(heading), math.sin(heading)
    body = np.array([c * delta[0] + s * delta[1], -s * delta[0] + c * delta[1]])
    error = math.atan2(math.sin(anchor_heading - heading), math.cos(anchor_heading - heading))
    return [*np.clip(body * 0.8, -0.12, 0.12).tolist(), float(np.clip(error, -0.3, 0.3))]


def follow_command(base, heading, path):
    """Legacy helper retained for offline comparisons; the goal runner uses PathFollower."""
    while len(path) > 1 and math.dist(base[:2], path[0]) < 0.08:
        path.pop(0)
    dx, dy = np.asarray(path[0]) - np.asarray(base[:2])
    error = math.atan2(
        math.sin(math.atan2(dy, dx) - heading), math.cos(math.atan2(dy, dx) - heading)
    )
    return [0.20 * max(0, math.cos(error)), 0.0, float(np.clip(error, -0.4, 0.4))]


class PathFollower:
    """Robot-local bounded lookahead; never changes a policy target or task budget."""

    def __init__(self, path, observation, target):
        self.path = [list(p) for p in path]
        self.floor, self.rects = rectangles(observation)
        # The planner ends at a grid center. Connect to the actual requested target
        # only through the same clearance check used during following.
        if self.path and math.dist(self.path[-1], target) > 1e-9:
            self.path.append(list(target))
        self.index = 0
        self.last = None

    def _window(self, index):
        yield index
        distance = 0.0
        for j in range(index + 1, len(self.path)):
            distance += math.dist(self.path[j - 1], self.path[j])
            if distance > LOOKAHEAD_M + 1e-9:
                break
            yield j

    def command(self, base, heading):
        if not self.path:
            raise ValueError("nonempty planned path required")

        def clear(point):
            return tracking_segment_clear(base, point, self.floor, self.rects)

        # Advance only to a nearer, directly reachable LOCAL path point. Never
        # search the whole route: a nearby later branch must not skip a detour.
        nearby = [j for j in self._window(self.index) if clear(self.path[j])]
        if nearby:
            nearest = min(nearby, key=lambda j: math.dist(base[:2], self.path[j]))
            self.index = nearest
        candidates = []
        for j in self._window(self.index):
            if not clear(self.path[j]):
                break  # do not look through a blocked corner
            candidates.append(j)
        selected = candidates[-1] if candidates else None
        command = [0.0, 0.0, 0.0]
        error = None
        if selected is not None:
            dx, dy = np.asarray(self.path[selected]) - np.asarray(base[:2])
            c, s = math.cos(heading), math.sin(heading)
            bx, by = c * dx + s * dy, -s * dx + c * dy
            error = math.atan2(by, bx)
            # Proportional speed can approach a close point without orbiting it.
            # Scale both axes together so clipping cannot redirect toward a wall.
            if bx >= -1e-9:
                vx, vy = max(0.0, 0.8 * bx), 0.8 * by
                scale = max(1.0, math.hypot(vx, vy) / 0.20, abs(vy) / 0.15)
                command[:2] = [float(vx / scale), float(vy / scale)]
            command[2] = float(np.clip(error, -0.4, 0.4))
        self.last = {
            "version": FOLLOWER_VERSION,
            "status": "tracking" if selected is not None else "blocked_connector",
            "path_index": self.index,
            "lookahead_index": selected,
            "lookahead_xy_m": self.path[selected] if selected is not None else None,
            "command_origin_xy_m": list(base[:2]),
            "command_origin_yaw_rad": float(heading),
            "heading_error_rad": error,
            "command_body": command,
        }
        return command


def escape_segment_clear(start, end, floor, rects):
    """Allow only a shallow, outward escape from an ALREADY infringed margin.

    For each nearby AABB, nonnegative directional derivative of squared distance
    at the start makes distance nondecreasing along the whole straight segment
    (squared distance to a convex set is convex). Other objects retain RADIUS.
    This is not permission to pass through a box or shrink the normal footprint.
    """
    if not all(math.isfinite(v) for v in (*start[:2], *end[:2])):
        return False
    if math.dist(start[:2], end[:2]) > CONNECTOR_LIMIT + 1e-9:
        return False
    if min(clearances(start, floor, rects)) < RADIUS - RECOVERY_MAX_INTRUSION:
        return False
    if min(clearances(end, floor, rects)) < PLANNING_RADIUS + 0.015:
        return False
    dx, dy = end[0] - start[0], end[1] - start[1]
    for rect in rects:
        if _rect_distance(start, rect) < PLANNING_RADIUS:
            a, b, c, d = rect
            qx, qy = min(b, max(a, start[0])), min(d, max(c, start[1]))
            if (start[0] - qx) * dx + (start[1] - qy) * dy < -1e-12:
                return False
        elif not segment_clear(start, end, [-math.inf, math.inf, -math.inf, math.inf], [rect]):
            return False
    return True


def recovery_target(base, target, floor, rects):
    if min(clearances(base, floor, rects)) >= PLANNING_RADIUS:
        return None
    for length in (0.15, 0.20, 0.25, 0.30, CONNECTOR_LIMIT):
        candidates = []
        for i in range(32):
            angle = 2 * math.pi * i / 32
            point = [base[0] + length * math.cos(angle), base[1] + length * math.sin(angle)]
            if escape_segment_clear(base, point, floor, rects):
                candidates.append(point)
        if candidates:
            return min(candidates, key=lambda p: math.dist(p, target))
    return None


class NavigationSession:
    """Bounded robot-local recovery. Runner owns the unchanged action deadline.

    Returning None ends this tool slice, not the task. No policy calls, teleports,
    scene edits, target substitutions or manipulation commands occur here.
    """

    def __init__(self, observation, target, initial_plan):
        self.target = list(target)
        self.initial_status = initial_plan["status"]
        self.floor, self.rects = rectangles(observation)
        self.follower = None
        if initial_plan["path_xy_m"]:
            self.follower = PathFollower(initial_plan["path_xy_m"], observation, target)
        self.can_execute = self.follower is not None or (
            initial_plan["status"] == "blocked_endpoint"
            and segment_clear(target, target, self.floor, self.rects)
            and recovery_target(observation.base_xyz_m, target, self.floor, self.rects) is not None
        )
        self.last = None
        self.stop_reason = None
        self.recovery = None
        self.recoveries = 0
        self.replans = 0
        self.events = []

    def _stop(self, reason, time_s):
        self.stop_reason = reason
        self.events.append(
            {"event": "tool_return", "simulation_time_s": float(time_s), "reason": reason}
        )
        self.last = {"version": FOLLOWER_VERSION, "status": reason, "command_body": None}
        return None

    def _replan(self, observation, time_s, trigger):
        if self.replans >= MAX_REPLANS:
            self._stop("replan_limit", time_s)
            return False
        self.replans += 1
        result = plan(observation, self.target)
        self.floor, self.rects = rectangles(observation)
        self.events.append(
            {
                "event": "replan",
                "simulation_time_s": float(time_s),
                "trigger": trigger,
                "base_xy_m": list(observation.base_xyz_m[:2]),
                "target_xy_m": self.target,
                "floor_xy_bounds_m": self.floor,
                "obstacle_xy_bounds_m": self.rects,
                "result": result,
            }
        )
        if not result["path_xy_m"]:
            self._stop("replan_" + result["status"], time_s)
            return False
        self.follower = PathFollower(result["path_xy_m"], observation, self.target)
        return True

    def command(self, base, heading, time_s, refresh):
        if self.stop_reason:
            return None
        if self.recovery is not None:
            observation = refresh()
            self.floor, self.rects = rectangles(observation)
            current = clearances(base, self.floor, self.rects)
            recovery = self.recovery
            if len(current) != len(recovery["clearances"]) or any(
                now < min(before, PLANNING_RADIUS) - 0.02
                for now, before in zip(current, recovery["clearances"], strict=False)
            ):
                return self._stop("recovery_clearance_worsened", time_s)
            if math.dist(base[:2], recovery["start_xy_m"]) > CONNECTOR_LIMIT:
                return self._stop("recovery_distance_limit", time_s)
            if min(current) >= PLANNING_RADIUS + 0.015:
                self.events.append(
                    {
                        "event": "recovery_completed",
                        "simulation_time_s": float(time_s),
                        "base_xy_m": list(base[:2]),
                        "clearance_m": min(current),
                    }
                )
                self.recovery = None
                if not self._replan(observation, time_s, "clearance_recovered"):
                    return None
            else:
                if time_s - recovery["start_s"] >= RECOVERY_MAX_SECONDS:
                    return self._stop("recovery_timeout", time_s)
                remaining = math.dist(base[:2], recovery["target_xy_m"])
                if remaining < recovery["best_remaining_m"] - 0.005:
                    recovery["best_remaining_m"] = remaining
                    recovery["progress_s"] = time_s
                if time_s - recovery["progress_s"] >= 1.0:
                    return self._stop("recovery_no_progress", time_s)
                if not escape_segment_clear(base, recovery["target_xy_m"], self.floor, self.rects):
                    return self._stop("recovery_connector_blocked", time_s)
                dx, dy = np.asarray(recovery["target_xy_m"]) - np.asarray(base[:2])
                speed = min(RECOVERY_SPEED, remaining * 2.0)
                c, s = math.cos(heading), math.sin(heading)
                command = [
                    float(speed * (c * dx + s * dy) / remaining),
                    float(speed * (-s * dx + c * dy) / remaining),
                    0.0,
                ]
                self.last = {
                    "version": FOLLOWER_VERSION,
                    "status": "clearance_recovery",
                    "recovery_target_xy_m": recovery["target_xy_m"],
                    "command_origin_xy_m": list(base[:2]),
                    "command_origin_yaw_rad": float(heading),
                    "minimum_clearance_m": min(current),
                    "command_body": command,
                }
                return command
        if self.follower is not None:
            command = self.follower.command(base, heading)
            self.last = self.follower.last
            if self.last["status"] != "blocked_connector":
                return command

        observation = refresh()
        self.floor, self.rects = rectangles(observation)
        minimum = min(clearances(base, self.floor, self.rects))
        self.events.append(
            {
                "event": "blocked_connector",
                "simulation_time_s": float(time_s),
                "base_xy_m": list(base[:2]),
                "minimum_clearance_m": minimum,
            }
        )
        if self.replans >= MAX_REPLANS:
            return self._stop("replan_limit", time_s)
        if minimum < PLANNING_RADIUS:
            point = recovery_target(base, self.target, self.floor, self.rects)
            if point is None:
                return self._stop("no_safe_clearance_recovery", time_s)
            self.recoveries += 1
            self.recovery = {
                "start_s": time_s,
                "start_xy_m": list(base[:2]),
                "target_xy_m": point,
                "clearances": clearances(base, self.floor, self.rects),
                "best_remaining_m": math.dist(base[:2], point),
                "progress_s": time_s,
            }
            self.events.append(
                {
                    "event": "recovery_started",
                    "simulation_time_s": float(time_s),
                    "base_xy_m": list(base[:2]),
                    "recovery_target_xy_m": point,
                    "minimum_clearance_m": minimum,
                    "floor_xy_bounds_m": self.floor,
                    "obstacle_xy_bounds_m": self.rects,
                }
            )
            return self.command(base, heading, time_s, refresh)
        if not self._replan(observation, time_s, "blocked_connector"):
            return None
        command = self.follower.command(base, heading)
        self.last = self.follower.last
        if self.last["status"] == "blocked_connector":
            return self._stop("blocked_after_replan", time_s)
        return command

    def audit(self, time_s, terminal_reason=None):
        return {
            "version": FOLLOWER_VERSION,
            "recovery_count": self.recoveries,
            "replan_count": self.replans,
            "status": (self.initial_status if not self.can_execute else self.stop_reason)
            or ("recovery_interrupted" if self.recovery else "tracking_slice_ended"),
            "ended_at_simulation_s": float(time_s),
            "terminal_reason": terminal_reason,
            "events": [
                {
                    k: v
                    for k, v in e.items()
                    if k not in {"result", "floor_xy_bounds_m", "obstacle_xy_bounds_m"}
                }
                | ({"plan_status": e["result"]["status"]} if "result" in e else {})
                for e in self.events
            ],
        }
