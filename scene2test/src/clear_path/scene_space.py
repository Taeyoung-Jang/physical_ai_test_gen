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


def axes_for_schema(schema="clear-path-fixture-v1"):
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
