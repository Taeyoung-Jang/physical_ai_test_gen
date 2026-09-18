"""Action-specific wire schema: API and local parser share identical typed variants."""

from typing import Literal

from pydantic import Field

from .goal_policy import GoalAction
from .policy import Action, Strict


class Navigate(GoalAction):
    action: Literal["navigate_to", "plan_path"]
    target_xy_m: list[float] = Field(min_length=2, max_length=2)
    skill_request: None
    vx_mps: float = Field(ge=0, le=0)
    vy_mps: float = Field(ge=0, le=0)
    yaw_rate_rps: float = Field(ge=0, le=0)


class Move(GoalAction):
    action: Literal["move"]
    target_xy_m: None
    skill_request: None
    duration_s: float = Field(ge=0.2, le=2)


class Passive(GoalAction):
    action: Literal["observe", "stop"]
    target_xy_m: None
    skill_request: None
    vx_mps: float = Field(ge=0, le=0)
    vy_mps: float = Field(ge=0, le=0)
    yaw_rate_rps: float = Field(ge=0, le=0)


class Skill(Passive):
    action: Literal["request_skill"]
    skill_request: str = Field(min_length=1, max_length=600)


class GoalEnvelope(Strict):
    command: Navigate | Move | Passive | Skill


class VelocityMove(Action):
    action: Literal["move"]


class VelocityPassive(Action):
    action: Literal["observe", "stop"]
    vx_mps: float = Field(ge=0, le=0)
    vy_mps: float = Field(ge=0, le=0)
    yaw_rate_rps: float = Field(ge=0, le=0)


class VelocityEnvelope(Strict):
    command: VelocityMove | VelocityPassive


def schema(envelope):
    value = envelope.model_json_schema()

    def walk(node):
        if isinstance(node, dict):
            if "const" in node:
                node["enum"] = [node.pop("const")]
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return value
