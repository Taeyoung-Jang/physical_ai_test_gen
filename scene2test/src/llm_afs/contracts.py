"""Fail-closed proposal contract. LLM output cannot change robot/task or generator code."""

import json
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from procedural_world.core import navigation_map, scene_graph
from procedural_world.terrain import generate_course
from procedural_world.terrain_presets import apply_parameters


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Range(StrictModel):
    path: str
    low: float
    high: float

    @model_validator(mode="after")
    def ordered(self):
        if self.low > self.high:
            raise ValueError("range low must not exceed high")
        return self


class Value(StrictModel):
    path: str
    value: float


class Candidate(StrictModel):
    values: list[Value] = Field(min_length=1, max_length=16)


class Proposal(StrictModel):
    schema_version: Literal["failure-space-proposal-v1"]
    base_scene_revision: str
    hypothesis: str = Field(min_length=1, max_length=2000)
    ranges: list[Range] = Field(min_length=1, max_length=16)
    representatives: list[Candidate] = Field(min_length=1, max_length=8)


class Config(StrictModel):
    course: dict[str, Any]
    domains: list[Range] = Field(min_length=1, max_length=16)
    robot_spec: dict[str, Any]
    policy_spec: dict[str, Any]
    observation_spec: dict[str, Any]
    task_spec: dict[str, Any]

    @model_validator(mode="after")
    def valid_context(self):
        json.dumps(self.model_dump(), allow_nan=False)
        expected = {
            "schema": "navigation@1.0",
            "physics_timestep_s": 0.005,
            "settling_duration_s": 1.0,
        }
        if any(self.task_spec.get(k) != v for k, v in expected.items()):
            raise ValueError("task does not match the supported isolated runner")
        for key, low, high in (("speed_mps", 0.05, 0.4), ("maximum_duration_s", 1, 600)):
            value = self.task_spec.get(key)
            if type(value) not in (int, float) or not low <= value <= high:
                raise ValueError("invalid frozen execution parameter")
        if (
            self.robot_spec.get("id") != "unitree_g1_locomotion"
            or self.policy_spec.get("policy_id") != "groot_walk_policy"
            or self.policy_spec.get("upper_level") != "gt-waypoint-terrain-v1"
            or self.policy_spec.get("robot_vlm_enabled") is not False
            or self.observation_spec.get("map") != "full_ground_truth_navigation_map"
            or self.observation_spec.get("localization") != "simulator_ground_truth_pose"
            or self.observation_spec.get("camera_to_policy") is not False
        ):
            raise ValueError("only the existing GT terrain policy is executable in v1")
        paths = [d.path for d in self.domains]
        if len(set(paths)) != len(paths):
            raise ValueError("duplicate domain path")
        allowed_global = {"width_m", "friction"}
        allowed_segment = {
            "flat": {"length_m", "width_m", "friction"},
            "ramp": {"angle_deg", "length_m", "landing_m", "width_m", "friction"},
            "stairs": {"step_height_m", "tread_m", "landing_m", "width_m", "friction"},
            "friction": {"length_m", "width_m", "friction"},
            "rough": {"length_m", "amplitude_m", "cell_length_m", "width_m", "friction"},
            "bottleneck": {"length_m", "gap_m", "width_m", "friction"},
            "obstacles": {"length_m", "width_m", "friction"},
        }
        for d in self.domains:
            parts = d.path.split(".")
            if len(parts) == 1 and d.path in allowed_global:
                value = self.course[d.path]
            elif len(parts) == 3 and parts[0] == "segments" and parts[1].isdigit():
                i = int(parts[1])
                if str(i) != parts[1] or i >= len(self.course["segments"]):
                    raise ValueError("invalid segment index")
                section = self.course["segments"][i]
                if parts[2] not in allowed_segment.get(section["kind"], set()):
                    raise ValueError("unsupported editable field")
                value = section[parts[2]]
            else:
                raise ValueError("unsupported editable path")
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("editable fields must be finite numbers")
            if not d.low <= value <= d.high:
                raise ValueError("base value must lie in its domain")
            # Generator enforces physical numeric limits too, before any API call.
            for bound in (d.low, d.high):
                derived = generate_course(apply_parameters(self.course, {d.path: bound}))
                base = generate_course(self.course)
                if (derived.spawn_xy, derived.goal_xy) != (base.spawn_xy, base.goal_xy):
                    raise ValueError("domain must preserve fixed task endpoints")
        spec = generate_course(self.course)
        if not navigation_map(spec)["reachable"]:
            raise ValueError("base course must have a static path")
        return self


def unique_by_path(items):
    result = {item.path: item for item in items}
    if len(result) != len(items):
        raise ValueError("duplicate parameter path")
    return result


def validate_proposal(config: Config, proposal: Proposal):
    base = generate_course(config.course)
    if proposal.base_scene_revision != base.revision:
        raise ValueError("proposal base revision mismatch")
    domain = unique_by_path(config.domains)
    ranges = unique_by_path(proposal.ranges)
    for path, r in ranges.items():
        if path not in domain or not domain[path].low <= r.low <= r.high <= domain[path].high:
            raise ValueError("proposal exceeds allowed domain")
    for candidate in proposal.representatives:
        values = unique_by_path(candidate.values)
        if values.keys() != ranges.keys():
            raise ValueError("representative must supply exactly the proposed paths")
        for path, item in values.items():
            if not ranges[path].low <= item.value <= ranges[path].high:
                raise ValueError("representative outside proposed range")
    return proposal


def context(config: Config, observations: list[dict] | None = None):
    spec = generate_course(config.course)
    nav = navigation_map(spec)
    return {
        "schema_version": "llm-afs-context-v1",
        "base_scene_revision": spec.revision,
        "scene_graph": scene_graph(spec).to_dict(),
        "scene_spec": spec.to_dict(),
        "course": config.course,
        "allowed_domains": [d.model_dump() for d in config.domains],
        "robot_spec": config.robot_spec,
        "policy_spec": config.policy_spec,
        "observation_spec": config.observation_spec,
        "task_spec": config.task_spec,
        "task_endpoints": {"spawn_xy_m": spec.spawn_xy, "goal_xy_m": spec.goal_xy},
        "navigation_summary": {
            "path_length_m": nav["path_length_m"],
            "static_path_exists": nav["reachable"],
        },
        "constraints": {
            "fixed": [
                "robot",
                "policy",
                "task",
                "seed",
                "segment_order",
                "segment_kinds",
                "planning_limits",
                "all fields not in allowed_domains",
            ],
            "execution_route": "isolated_terrain_runner_only",
            "geometry_invalid_is_robot_failure": False,
            "proposal_is_confirmed_failure": False,
        },
        "observations": observations or [],
    }


def proposal_schema(config: Config):
    schema = Proposal.model_json_schema()
    paths = [d.path for d in config.domains]
    for name in ("Range", "Value"):
        schema["$defs"][name]["properties"]["path"]["enum"] = paths
    schema["properties"]["base_scene_revision"]["enum"] = [generate_course(config.course).revision]
    return schema
