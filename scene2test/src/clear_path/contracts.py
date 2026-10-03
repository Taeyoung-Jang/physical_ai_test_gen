"""Explicit task and action contracts, deliberately separate from navigation@1.0."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Fixture(Strict):
    schema_version: Literal["clear-path-fixture-v1"] = "clear-path-fixture-v1"
    box_mass_kg: float = Field(default=2.0, ge=0.2, le=10.0)
    box_friction: float = Field(default=0.5, ge=0.05, le=1.5)
    floor_friction: float = Field(default=0.8, ge=0.05, le=1.5)
    footprint_radius_m: float = Field(default=0.35, ge=0.3, le=0.4)
    clearance_m: float = Field(default=0.05, ge=0.03, le=0.1)
    # Geometry is intentionally fixed for the first controlled fixture.


class CorridorFixture(Fixture):
    """Opt-in rectangular corridor; box dimensions, robot and goal stay fixed."""

    schema_version: Literal["clear-path-corridor-v2"] = "clear-path-corridor-v2"
    corridor_width_m: float = Field(default=4.0, ge=1.6, le=4.0)
    box_lateral_fraction: float = Field(default=0.0, ge=-1.0, le=1.0)


class ObstacleFixture(CorridorFixture):
    """Two fixed, oriented blocks plus the existing movable box. No new robot skills.

    Disjoint X bands keep every bounded sample clear of the spawn, goal and initial
    box. Lateral fractions use each block's rotated AABB and a 5 cm wall gap.
    All 17 axes are continuous: no rejection sampling or hidden active-slot switch.
    """

    schema_version: Literal["clear-path-obstacles-v3"] = "clear-path-obstacles-v3"
    obstacle_1_x_m: float = Field(default=2.5, ge=2.25, le=2.75)
    obstacle_1_lateral_fraction: float = Field(default=0.7, ge=-1.0, le=1.0)
    obstacle_1_size_x_m: float = Field(default=0.5, ge=0.2, le=0.8)
    obstacle_1_size_y_m: float = Field(default=0.5, ge=0.2, le=0.8)
    obstacle_1_height_m: float = Field(default=0.6, ge=0.1, le=1.2)
    obstacle_1_yaw_deg: float = Field(default=0.0, ge=-90.0, le=90.0)
    obstacle_2_x_m: float = Field(default=5.5, ge=5.25, le=5.75)
    obstacle_2_lateral_fraction: float = Field(default=-0.7, ge=-1.0, le=1.0)
    obstacle_2_size_x_m: float = Field(default=0.5, ge=0.2, le=0.8)
    obstacle_2_size_y_m: float = Field(default=0.5, ge=0.2, le=0.8)
    obstacle_2_height_m: float = Field(default=0.6, ge=0.1, le=1.2)
    obstacle_2_yaw_deg: float = Field(default=0.0, ge=-90.0, le=90.0)


class GoalRegionFixture(ObstacleFixture):
    """Move the SAME dynamic box near the unchanged goal; no extra object or skill.

    At X>=6.8 its left edge is beyond the maximum rotated obstacle-2 edge
    (6.316m); at X<=7.5 its right edge leaves 10cm to the end wall. All bounded
    samples are initially non-overlapping without path/occupancy rejection.
    """

    schema_version: Literal["clear-path-goal-region-v4"] = "clear-path-goal-region-v4"
    box_goal_x_m: float = Field(default=7.0, ge=6.8, le=7.5)


def parse_fixture(value=None):
    if value is None:
        return Fixture()
    if isinstance(value, Fixture):
        value = value.model_dump()
    if not isinstance(value, dict):
        raise ValueError("scene configuration must be an object")
    cls = {
        "clear-path-corridor-v2": CorridorFixture,
        "clear-path-obstacles-v3": ObstacleFixture,
        "clear-path-goal-region-v4": GoalRegionFixture,
    }.get(value.get("schema_version"), Fixture)
    return cls.model_validate(value)


class Action(Strict):
    schema_version: Literal["clear-path-action-v1"]
    action: Literal["navigate_to", "push_object", "observe", "stop"]
    state_version: int = Field(ge=0)
    object_id: str | None
    target_xy_m: list[float] | None

    @model_validator(mode="after")
    def valid_shape(self):
        if self.action in {"navigate_to", "push_object"}:
            if self.target_xy_m is None or len(self.target_xy_m) != 2:
                raise ValueError("motion action requires a finite 2D world-m target")
        elif self.target_xy_m is not None:
            raise ValueError("observe/stop cannot carry a motion target")
        if (self.action == "push_object") != (self.object_id is not None):
            raise ValueError("only push_object requires an object ID")
        return self


def validate_action(action, *, state_version, enabled_actions=(), object_ids=("clear_box",)):
    """Contract guard only; this does NOT certify reachability or execute an action."""
    if action.state_version != state_version:
        raise ValueError("stale action state_version")
    if action.action not in enabled_actions:
        raise ValueError("action executor unavailable")
    if action.object_id is not None and action.object_id not in object_ids:
        raise ValueError("unknown object")
    if action.target_xy_m is not None:
        x, y = action.target_xy_m
        if not (0.1 <= x <= 7.9 and -0.7 <= y <= 2.4):
            raise ValueError("target outside workspace envelope")


def evaluate(*, valid, goal_reached, path_open, fallen, forbidden_contact):
    """Consume measured facts; never a model's predicted success."""
    if any(
        type(v) is not bool for v in (valid, goal_reached, path_open, fallen, forbidden_contact)
    ):
        raise ValueError("measured facts must be booleans")
    if not valid:
        return {"verdict": "INDETERMINATE", "task_success": None}
    success = goal_reached and path_open and not fallen and not forbidden_contact
    return {"verdict": "PASS" if success else "FAIL", "task_success": bool(success)}
