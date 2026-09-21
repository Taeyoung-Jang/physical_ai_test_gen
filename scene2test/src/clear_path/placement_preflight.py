"""Measured box-state maps and conservative straight-push preflight.

No motion execution, simulator stepping, or full-body feasibility certification.
"""

import hashlib
import json
from collections import deque

import numpy as np

from . import fixture


def navigation_map(config, box_bounds):
    bounds = np.asarray(box_bounds, dtype=float)
    if bounds.shape != (4,) or not np.isfinite(bounds).all():
        raise ValueError("finite xmin/xmax/ymin/ymax required")
    if bounds[0] >= bounds[1] or bounds[2] >= bounds[3]:
        raise ValueError("ordered nonempty box bounds required")
    res, origin = 0.05, [-0.1, -1.0]
    x, y = np.meshgrid(
        (np.arange(164) + 0.5) * res + origin[0], (np.arange(74) + 0.5) * res + origin[1]
    )
    inside = ((x >= 0) & (x <= 8) & (y >= -0.8) & (y <= 0.8)) | (
        (x >= 3.3) & (x <= 4.7) & (y >= 0.8) & (y <= 2.5)
    )
    blocked = ~inside
    radius = config.footprint_radius_m + config.clearance_m
    for x0, x1, y0, y1 in [*fixture.WALLS.values(), bounds]:
        dx = np.maximum(np.maximum(x0 - x, x - x1), 0)
        dy = np.maximum(np.maximum(y0 - y, y - y1), 0)
        blocked |= dx * dx + dy * dy <= radius * radius

    def cell(xy):
        return int((xy[1] - origin[1]) / res), int((xy[0] - origin[0]) / res)

    start, goal = cell(fixture.SPAWN), cell(fixture.GOAL)
    parents = {start: None} if not blocked[start] else {}
    queue = deque(parents)
    while queue:
        a = queue.popleft()
        if a == goal:
            break
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            b = a[0] + dy, a[1] + dx
            if (
                0 <= b[0] < blocked.shape[0]
                and 0 <= b[1] < blocked.shape[1]
                and b not in parents
                and not blocked[b]
            ):
                parents[b] = a
                queue.append(b)
    path, node = [], goal if goal in parents else None
    while node is not None:
        path.append([float(x[node]), float(y[node])])
        node = parents[node]
    return {
        "schema_version": "clear-path-measured-map-v1",
        "frame": "world_m",
        "resolution_m": res,
        "origin_xy_m": origin,
        "effective_radius_m": radius,
        "box_bounds_xy_m": bounds.tolist(),
        "blocked": blocked.astype(int).tolist(),
        "reachable": bool(path),
        "path_xy_m": path[::-1],
        "note": "Conservative rotated-box world AABB; not full-body feasibility",
    }


def direct_push_preflight(config):
    """Check a south-face straight push toward +Y; no claim about other strategies."""
    radius = config.footprint_radius_m + config.clearance_m
    face_y = fixture.BOX_START[1] - fixture.BOX_SIZE[1] / 2
    wall_y = fixture.WALLS["wall_south"][3]
    gap = face_y - wall_y
    # Current validated palm offset is only 0.24..0.30 m in front of the base.
    stance_y = face_y - 0.28
    return {
        "schema_version": "clear-path-placement-preflight-v1",
        "scene_revision": fixture.identity(config),
        "strategy": "south-face straight push toward north bay (+Y)",
        "decision": "REJECT_UNDER_CURRENT_APPROACH_MODEL" if gap < 2 * radius else "UNVERIFIED",
        "robot_execution_authorized": False,
        "south_gap_m": gap,
        "required_footprint_width_m": 2 * radius,
        "gap_deficit_m": max(0.0, 2 * radius - gap),
        "candidate_base_xy_m": [fixture.BOX_START[0], stance_y],
        "south_wall_inner_y_m": wall_y,
        "candidate_base_outside_corridor": stance_y < wall_y,
        "other_strategies": "not evaluated; no global impossibility claim",
        "current_executor": "world +X near-box only; +Y/heading transform unvalidated",
        "required_next_decision": "new revision with south staging space OR new corner/side skill",
        "note": "80 cm is an assumed circular planning envelope, not measured robot width",
    }


def snapshot(model, qpos, config, *, state_version, source):
    import mujoco

    qpos = np.asarray(qpos, dtype=float)
    if qpos.shape != (model.nq,) or not np.isfinite(qpos).all():
        raise ValueError("finite complete qpos required")
    if type(state_version) is not int or state_version < 0:
        raise ValueError("nonnegative integer state_version required")
    # Fail closed on a different fixture; no map/XML drift allowed.
    for name, (a, b, c, d) in fixture.WALLS.items():
        g = model.geom(name)
        if not (
            np.allclose(g.pos, [(a + b) / 2, (c + d) / 2, 0.6])
            and np.allclose(g.size, [(b - a) / 2, (d - c) / 2, 0.6])
        ):
            raise ValueError("fixture wall geometry mismatch")
    data = mujoco.MjData(model)
    data.qpos[:] = qpos
    mujoco.mj_forward(model, data)  # derived geometry only, zero integration steps
    geom = data.geom("clear_box_geom")
    half = model.geom("clear_box_geom").size
    if not np.allclose(2 * half, fixture.BOX_SIZE):
        raise ValueError("fixture box geometry mismatch")
    rotation = geom.xmat.reshape(3, 3)
    extents = np.abs(rotation) @ half  # includes yaw, roll and pitch
    center = geom.xpos.copy()
    bounds = [
        center[0] - extents[0],
        center[0] + extents[0],
        center[1] - extents[1],
        center[1] + extents[1],
    ]
    graph = fixture.graph(config)
    box = next(o for o in graph["objects"] if o["id"] == "clear_box")
    box["position"], box["size"] = center.tolist(), (2 * extents).tolist()
    box["extra"].update(
        {
            "world_rotation_matrix": rotation.tolist(),
            "local_size_m": list(fixture.BOX_SIZE),
            "size_semantics": "world_AABB",
        }
    )
    scene_state = {
        "state_version": state_version,
        "source": source,
        "qpos": qpos.tolist(),
        "scene_revision": fixture.identity(config),
    }
    digest = hashlib.sha256(json.dumps(scene_state, sort_keys=True).encode()).hexdigest()
    shared = {
        "state_version": state_version,
        "state_digest": digest,
        "source": source,
        "scene_revision": fixture.identity(config),
        "hypothetical": False,
    }
    graph["meta"].update(shared)
    graph["meta"]["robot_rollout"] = True
    nav = navigation_map(config, bounds)
    nav.update(shared)
    return {
        "scene_graph": graph,
        "navigation_map": nav,
        "box_position_m": center.tolist(),
        "state": scene_state,
    }
