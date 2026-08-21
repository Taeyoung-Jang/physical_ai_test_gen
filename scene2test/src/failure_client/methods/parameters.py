"""Reusable parameter spaces and intent rendering for baseline methods."""

from __future__ import annotations

import copy
import math
from typing import Any, Literal

import numpy as np
from pydantic import Field, model_validator

from failure_client.contracts import ContractModel


class ParameterSpec(ContractModel):
    kind: Literal["continuous", "integer", "categorical"] = "continuous"
    low: float | int | None = None
    high: float | int | None = None
    choices: list[Any] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_domain(self) -> ParameterSpec:
        if self.kind in {"continuous", "integer"}:
            if self.low is None or self.high is None or self.low > self.high:
                raise ValueError("numeric parameter requires low <= high")
        elif not self.choices:
            raise ValueError("categorical parameter requires choices")
        return self


class ParametricMethodConfig(ContractModel):
    operation: str = "add_primitive"
    operation_version: str = "1.0"
    coordinate_frame: str = "scene"
    parameter_space: dict[str, ParameterSpec]
    static_parameters: dict[str, Any] = Field(default_factory=dict)
    parameter_bindings: dict[str, str] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    maximum_candidates: int | None = Field(default=None, gt=0)


def sample_with_rng(spec: ParameterSpec, rng: np.random.Generator) -> Any:
    if spec.kind == "continuous":
        return float(rng.uniform(float(spec.low), float(spec.high)))
    if spec.kind == "integer":
        return int(rng.integers(int(spec.low), int(spec.high) + 1))
    return spec.choices[int(rng.integers(0, len(spec.choices)))]


def sample_from_unit(spec: ParameterSpec, value: float) -> Any:
    value = min(max(float(value), 0.0), math.nextafter(1.0, 0.0))
    if spec.kind == "continuous":
        return float(spec.low) + (float(spec.high) - float(spec.low)) * value
    if spec.kind == "integer":
        count = int(spec.high) - int(spec.low) + 1
        return int(spec.low) + min(int(value * count), count - 1)
    return spec.choices[min(int(value * len(spec.choices)), len(spec.choices) - 1)]


def render_parameters(config: ParametricMethodConfig, sampled: dict[str, Any]) -> dict[str, Any]:
    parameters = copy.deepcopy(config.static_parameters)
    for name, value in sampled.items():
        path = config.parameter_bindings.get(name, name)
        _set_path(parameters, path, value)
    return parameters


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current: Any = target
    for index, part in enumerate(parts[:-1]):
        next_part = parts[index + 1]
        if isinstance(current, list):
            current = current[int(part)]
        else:
            if part not in current:
                current[part] = [] if next_part.isdigit() else {}
            current = current[part]
    final = parts[-1]
    if isinstance(current, list):
        position = int(final)
        while len(current) <= position:
            current.append(None)
        current[position] = value
    else:
        current[final] = value

