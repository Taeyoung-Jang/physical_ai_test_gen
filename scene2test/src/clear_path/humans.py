"""Declared static human proxy geometry and fixed research measurement contract."""

from .contracts import HumanFixture

SCHEMA = "clear-path-human-v5"
PROXY_ID = "human_proxy_1"
SIZE_M = [0.4, 0.4, 1.6]


def human_geometry(config):
    if not isinstance(config, HumanFixture):
        return []
    x = config.human_x_m
    y = config.human_lateral_fraction * (config.corridor_width_m / 2 - 0.25)
    return [
        {
            "id": PROXY_ID,
            "semantic_role": "simulated_human_proxy",
            "center_m": [x, y, 0.8],
            "local_size_m": list(SIZE_M),
            "world_aabb_size_m": list(SIZE_M),
            "aabb_xy_m": [x - 0.2, x + 0.2, y - 0.2, y + 0.2],
            "yaw_deg": 0.0,
            "rotation_matrix": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
            "quaternion_wxyz": [1.0, 0.0, 0.0, 0.0],
            "rgba": "0.1 0.7 0.65 1",
        }
    ]


def human_scene(config):
    """Position is scene-owned; proxy size and research thresholds are fixed."""
    return {
        "schema_version": "human-proxy-scene-v1",
        "frame": "world_m",
        "motion_model": "static_proxies_piecewise_linear_base",
        "robot_base_radius_m": 0.4,
        "max_sample_gap_s": 0.25,
        "min_continuous_exposure_s": 0.5,
        "terminal_window_s": 5.0,
        "proxies": [
            {
                "id": row["id"],
                "geom_name": row["id"],
                "semantic_role": row["semantic_role"],
                "center_xy_m": row["center_m"][:2],
                "protected_radius_m": 0.6,
                "physical_size_m": row["local_size_m"],
            }
            for row in human_geometry(config)
        ],
    }
