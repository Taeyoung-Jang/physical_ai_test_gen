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
