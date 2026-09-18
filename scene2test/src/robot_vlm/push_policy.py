"""Opt-in typed short-push capability; the policy chooses its own strategy."""

import json
from typing import Literal

from pydantic import Field

from .goal_policy import GoalMock, GoalPolicy
from .policy import Strict
from .wire_contract import Move, Navigate, Passive, Skill, schema

PROMPT_VERSION = "goal-agent-push-v3"


class PushAction(Strict):
    state_version: int = Field(ge=0)
    plan_summary: str = Field(max_length=600)
    action: Literal["push_object"]
    object_id: Literal["clear_box_geom"]
    target_xy_m: list[float] = Field(min_length=2, max_length=2)
    skill_request: None
    vx_mps: float = Field(ge=0, le=0)
    vy_mps: float = Field(ge=0, le=0)
    yaw_rate_rps: float = Field(ge=0, le=0)
    duration_s: float = Field(ge=18, le=18)


class PushEnvelope(Strict):
    command: Navigate | Move | Passive | Skill | PushAction


class PushPolicy(GoalPolicy):
    def body(self, observation, png):
        body = super().body(observation, png)
        body["text"]["format"]["schema"] = schema(PushEnvelope)
        body["instructions"] += """
An experimental push_object executor is installed. Choose whether to use it and
select the object target yourself. It does not autonomously approach or rotate.
Observe the documented preconditions; unsupported requests return measured feedback.
Only designated hand/object contact during this skill is permitted. Grasp, carry,
jump and arbitrary-direction pushing remain unavailable. Do not assume moving an
object clears a route: query the internal planner again using the updated observation.
"""
        text = body["input"][0]["content"][0]
        context = json.loads(text["text"])
        context["capabilities"]["push_object"] = {
            "version": "near-contact-push-v1",
            "object_id": "clear_box_geom",
            "target": "desired object center XY in world meters, not robot destination",
            "duration_s": 18,
            "additional_handoff_s": 3,
            "preconditions": {
                "box_size_m": [0.8, 1.1, 0.7],
                "forward_displacement_m": [0.075, 0.20],
                "base_to_box_center_forward_m": [0.72, 0.90],
                "maximum_lateral_offset_m": 0.06,
                "maximum_heading_and_box_face_error_rad": 0.12,
                "base_height_m": [0.65, 0.85],
                "box_center_height_m": [0.30, 0.40],
            },
            "limitations": "near aligned approach required; short forward push only",
        }
        context["constraints"] = (
            "No falls or forbidden contacts. Only hands with selected box during push are allowed; "
            "per-contact force <=120N. No grasp/carry/jump. No guarantee of clearing the path."
        )
        text["text"] = json.dumps(context, allow_nan=False)
        return body

    def decide(self, observation, png):
        from .api_transport import call

        return call(
            self.body(observation, png),
            lambda value: PushEnvelope.model_validate(value).command,
            transport=self.transport,
        )


class PushMock(PushPolicy, GoalMock):
    """Default mock retains navigation-only fixture; no claim of push autonomy."""

    decide = GoalMock.decide

