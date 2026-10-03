"""Versioned scene-only search domains shared by sampling, feedback and validation."""

from .contracts import parse_fixture

PHYSICS_AXES = {
    "box_mass_kg": (0.2, 10.0),
    "box_friction": (0.05, 1.5),
    "floor_friction": (0.05, 1.5),
}
CORRIDOR_AXES = {
    **PHYSICS_AXES,
    "corridor_width_m": (1.6, 4.0),
    "box_lateral_fraction": (-1.0, 1.0),
}


OBSTACLE_AXES = {
    **CORRIDOR_AXES,
    **{
        f"obstacle_{i}_{axis}": bounds
        for i in (1, 2)
        for axis, bounds in {
            "x_m": (2.25, 2.75) if i == 1 else (5.25, 5.75),
            "lateral_fraction": (-1.0, 1.0),
            "size_x_m": (0.2, 0.8),
            "size_y_m": (0.2, 0.8),
            "height_m": (0.1, 1.2),
            "yaw_deg": (-90.0, 90.0),
        }.items()
    },
}

GOAL_REGION_AXES = {**OBSTACLE_AXES, "box_goal_x_m": (6.8, 7.5)}
SCHEMAS = (
    "clear-path-fixture-v1",
    "clear-path-corridor-v2",
    "clear-path-obstacles-v3",
    "clear-path-goal-region-v4",
)


def axes_for_schema(schema="clear-path-fixture-v1"):
    if schema == "clear-path-goal-region-v4":
        return dict(GOAL_REGION_AXES)
    if schema == "clear-path-obstacles-v3":
        return dict(OBSTACLE_AXES)
    if schema == "clear-path-fixture-v1":
        return dict(PHYSICS_AXES)
    if schema == "clear-path-corridor-v2":
        return dict(CORRIDOR_AXES)
    raise ValueError("unsupported scene schema")


def axes_for_parameters(params):
    return axes_for_schema(params.get("schema_version", "clear-path-fixture-v1"))


def scene_from_parameters(params, schema="clear-path-fixture-v1"):
    if set(params) != set(axes_for_schema(schema)):
        raise ValueError("candidate must contain exactly the frozen scene axes")
    return parse_fixture({"schema_version": schema, **params})
