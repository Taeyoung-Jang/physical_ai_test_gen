"""Scene-owned block geometry, shared by XML, graph, maps and previews.

All dimensions are full local box extents; returned AABBs are conservative world
projections, not exact rotated footprints. No path-validity filtering is performed.
"""

import math

from .contracts import ObstacleFixture


def static_obstacles(config):
    if not isinstance(config, ObstacleFixture):
        return []
    rows = []
    for i in (1, 2):
        prefix = f"obstacle_{i}"
        x, fraction, sx, sy, height, yaw_deg = (
            getattr(config, f"{prefix}_{axis}")
            for axis in ("x_m", "lateral_fraction", "size_x_m", "size_y_m", "height_m", "yaw_deg")
        )
        angle = math.radians(yaw_deg)
        c, s = math.cos(angle), math.sin(angle)
        hx, hy = (abs(c) * sx + abs(s) * sy) / 2, (abs(s) * sx + abs(c) * sy) / 2
        y = fraction * (config.corridor_width_m / 2 - hy - 0.05)
        rows.append(
            {
                "id": prefix,
                "center_m": [x, y, height / 2],
                "local_size_m": [sx, sy, height],
                "world_aabb_size_m": [2 * hx, 2 * hy, height],
                "aabb_xy_m": [x - hx, x + hx, y - hy, y + hy],
                "yaw_deg": yaw_deg,
                "rotation_matrix": [c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0],
                # Independent of the source XML compiler's angle unit.
                "quaternion_wxyz": [math.cos(angle / 2), 0.0, 0.0, math.sin(angle / 2)],
            }
        )
    return rows
