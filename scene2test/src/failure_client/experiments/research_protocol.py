"""Frozen versioned scene-domain contract; no simulator or network imports."""

from __future__ import annotations

import platform
import xml.etree.ElementTree as ET
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from clear_path.scene_space import axes_for_schema, scene_from_parameters
from failure_client.evaluation.goal_run_reader import _hash_file
from failure_client.evaluation.research_records import StrictRecord
from llm_afs.behavior import digest

PROJECT = Path(__file__).resolve().parents[3]


class RobotSettings(StrictRecord):
    model: str = Field(default="gpt-6-astra", min_length=1)
    groot_root: str = "/workspace/g1_failure/src/GR00T-WholeBodyControl"
    max_calls: int = Field(default=10, ge=1, le=20)
    max_seconds: float | None = Field(default=None, ge=3)
    response_timeout: float = Field(default=300.0, ge=1, le=300)
    enable_push: bool = True
    navigation_completion: Literal["position_only_v1", "goal_dwell_v1"] = "position_only_v1"
    watchdog_wall_s: float | None = Field(default=None, gt=0)


class CampaignConfig(StrictRecord):
    schema_version: Literal["behavior-afs-campaign-v1"] = "behavior-afs-campaign-v1"
    scene_schema: Literal[
        "clear-path-fixture-v1",
        "clear-path-corridor-v2",
        "clear-path-obstacles-v3",
        "clear-path-goal-region-v4",
    ] = "clear-path-fixture-v1"
    seeds: list[int] = Field(default_factory=lambda: [17], min_length=1, max_length=20)
    valid_budget_per_seed: int = Field(default=8, ge=2, le=128)
    max_attempts_per_arm: int = Field(default=12, ge=2, le=256)
    cold_start: int = Field(default=2, ge=1)
    max_proposals_per_seed: int = Field(default=8, ge=1, le=128)
    afs_model: str = Field(default="gpt-6-astra", min_length=1)
    afs_timeout_s: float = Field(default=300.0, ge=1, le=600)
    history_limit: int = Field(default=8, ge=2, le=16)
    selection_policy: Literal["novelty-v1", "hypothesis-v2"] = "hypothesis-v2"
    taxonomy_profile: Literal["none", "goal-behavior-v1"] = "none"
    # A fixed pilot allocation, not ratios tuned after seeing the evaluation seed.
    strategy_cycle: list[Literal["llm", "boundary", "exploration", "repeat"]] = Field(
        default_factory=lambda: ["llm", "boundary", "exploration", "repeat"]
    )
    robot: RobotSettings = Field(default_factory=RobotSettings)

    @model_validator(mode="after")
    def consistent(self):
        if any(s < 0 for s in self.seeds) or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("distinct nonnegative search seeds required")
        if self.max_attempts_per_arm < self.valid_budget_per_seed:
            raise ValueError("attempt cap must cover the valid budget")
        if self.cold_start >= self.valid_budget_per_seed:
            raise ValueError("reserve at least one adaptive rollout after cold start")
        if sorted(self.strategy_cycle) != ["boundary", "exploration", "llm", "repeat"]:
            raise ValueError("pilot cycle must contain each of the four strategies exactly once")
        if not Path(self.robot.groot_root).is_absolute():
            raise ValueError("groot_root must be absolute")
        return self

    def design(self):
        axes = axes_for_schema(self.scene_schema)
        return {
            "domain_id": digest({"axes": axes, "fixture": self.scene_schema}),
            "axes": axes,
            "sampling_distribution": (
                "independent-uniform-full-three-axis-domain-v1"
                if self.scene_schema == "clear-path-fixture-v1"
                else "independent-uniform-full-five-axis-corridor-v2"
                if self.scene_schema == "clear-path-corridor-v2"
                else "independent-uniform-full-seventeen-axis-obstacles-v3"
                if self.scene_schema == "clear-path-obstacles-v3"
                else "independent-uniform-full-eighteen-axis-goal-region-v4"
            ),
            "cold_start": "paired scene draws, separately executed and charged to each arm",
            "strategy_cycle": self.strategy_cycle,
            "selection_policy": self.selection_policy,
            "taxonomy_profile": self.taxonomy_profile,
            "behavior_feedback": "behavior-search-evidence-v2: full actions + selected details",
            "fallback_policy": "stop; no silent Random substitution",
            "history_policy": "AFS arm's own seed only; no external warm history",
            "robot_repeat_seed": "not configurable in current runner; no determinism claim",
            "inference_time": "counts toward simulation; no default simulation time cap",
            "navigation_completion": self.robot.navigation_completion,
            "robot_api_call_upper_bound": (
                len(self.seeds) * 2 * self.max_attempts_per_arm * self.robot.max_calls
            ),
            "afs_request_upper_bound": len(self.seeds) * self.max_proposals_per_seed,
        }

    def scene(self, parameters):
        return scene_from_parameters(parameters, self.scene_schema)


def environment_fingerprint(config: CampaignConfig):
    """Freeze code, dependencies and XML/mesh/YAML/ONNX bytes before the first rollout.

    These are trusted-local checks, not a signed attestation or remote model snapshot.
    """
    sources = [
        PROJECT / "uv.lock",
        PROJECT / "pyproject.toml",
        PROJECT / "src/scene_graph.py",
        PROJECT / "tools/run_robot_goal_agent.py",
    ]
    sources.append(PROJECT / "tools/run_afs_benchmark.py")
    sources.append(PROJECT / "tools/run_afs_pilot.py")
    for folder in ("robot_vlm", "clear_path", "llm_afs", "failure_client", "simulation_server"):
        sources.extend(sorted((PROJECT / "src" / folder).rglob("*.py")))
    groot = Path(config.robot.groot_root).resolve()
    xml = groot / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    parsed = ET.parse(xml).getroot()
    if parsed.findall(".//include"):
        raise ValueError("included robot XML requires an explicit dependency resolver")
    if any(node.tag != "mesh" and node.get("file") for node in parsed.findall("asset/*")):
        raise ValueError("non-mesh external assets require an explicit dependency resolver")
    meshdir = xml.parent / parsed.find("compiler").get("meshdir", "")
    resources = [xml, xml.with_suffix(".yaml")]
    resources.extend(meshdir / e.get("file") for e in parsed.findall("asset/mesh"))
    resources.append(xml.parent / "policy/GR00T-WholeBodyControl-Walk.onnx")
    if any(not p.resolve().is_relative_to(groot) for p in resources):
        raise ValueError("robot resource escapes groot_root")
    return {
        "source_hashes": {str(p.relative_to(PROJECT)): _hash_file(p) for p in sources},
        "robot_resources": {str(p.resolve().relative_to(groot)): _hash_file(p) for p in resources},
        "python": platform.python_version(),
        "runtime_versions": {
            n: version(n)
            for n in (
                "mujoco",
                "numpy",
                "onnxruntime-gpu",
                "httpx",
                "pydantic",
                "imageio",
                "imageio-ffmpeg",
                "pillow",
                "pyyaml",
            )
        },
    }
