"""Freeze an independent evaluation design; no remote calls during preparation."""

from typing import Literal

from pydantic import Field, model_validator

from failure_client.evaluation.discovery_readiness import audit_discovery
from failure_client.evaluation.goal_run_reader import _hash_file
from failure_client.evaluation.research_records import StrictRecord
from failure_client.methods.autonomous_feedback import SearchBudget
from llm_afs.behavior import digest

from .afs_autonomous import development_plan, fingerprint
from .research_protocol import PROJECT


def evaluation_fingerprint(config):
    env = fingerprint(config)
    for name in (
        "run_discovery_evaluation.py",
        "prepare_discovery_evaluation.py",
        "run_discovery_continuation.py",
    ):
        env["source_hashes"][f"tools/{name}"] = _hash_file(PROJECT / "tools" / name)
    return env


class EvaluationDesign(StrictRecord):
    schema_version: Literal["joint-discovery-design-v1"] = "joint-discovery-design-v1"
    seeds: list[int] = Field(min_length=1, max_length=20)
    valid_per_seed: int = Field(default=20, ge=4, le=60)
    attempts_per_seed: int = Field(default=24, ge=4, le=72)
    afs_requests_per_seed: int = Field(default=24, ge=1, le=72)
    cold_start_per_seed: int = Field(default=2, ge=1)
    search: SearchBudget

    @model_validator(mode="after")
    def coherent(self):
        if len(set(self.seeds)) != len(self.seeds) or any(s < 0 for s in self.seeds):
            raise ValueError("predeclared distinct nonnegative seeds required")
        if not self.cold_start_per_seed < self.valid_per_seed <= self.attempts_per_seed:
            raise ValueError("cold start < valid target <= attempt cap required")
        if (
            self.search.valid_rollout_target != self.valid_per_seed
            or self.search.max_attempts != self.attempts_per_seed
            or self.search.max_afs_requests != self.afs_requests_per_seed
        ):
            raise ValueError("search and evaluation budgets must agree")
        if self.search.feedback_policy != "cause-review-v3":
            raise ValueError("evaluation proposal requires separated reference mode")
        return self


def evaluation_plan(paths, design, *, fingerprint_fn=None):
    locked = development_plan(
        paths, design.search, fingerprint_fn=fingerprint_fn or evaluation_fingerprint
    )
    p = locked["plan"]
    # Development inputs bind robot resources/settings ONLY. They are never evaluation history.
    config = p["target_config"]
    audit = audit_discovery(config["scene_schema"])
    n = len(design.seeds)
    manifest = {
        "schema_version": "joint-discovery-evaluation-manifest-v2",
        "design": design.model_dump(),
        "robot_config": config,
        "reference_condition_id": p["condition_id"],
        "reference_geometry_id": p["geometry_id"],
        "execution_origin": p["execution_origin"],
        "control_provenance": [
            {k: row[k] for k in ("evidence_id", "source", "artifact_hashes")}
            for row in p["history"]
        ],
        "environment": locked["environment"],
        "domain_audit": audit,
        "external_history_in_evaluation": [],
        "cold_start": (
            "Independent full-domain uniform per predeclared seed; separately executed and charged"
        ),
        "sampling_distribution": "independent-uniform-full-twenty-axis-human-v5"
        if config["scene_schema"] == "clear-path-human-v5"
        else "independent-uniform-full-declared-axis-domain",
        "valid_total": n * design.valid_per_seed,
        "attempt_cap_total": n * design.attempts_per_seed,
        "robot_api_call_upper_bound": n * design.attempts_per_seed * config["robot"]["max_calls"],
        "afs_request_upper_bound": n * design.afs_requests_per_seed,
        "targets": {"fdr": 0.3, "distinct_primary_families": 4, "family_inventory": 10},
        "gain_phase": "DEFERRED_SEPARATE_RANDOM_COMPARISON",
        "execution_readiness": "INDEPENDENT_RUNNER_IMPLEMENTED_NOT_LIVE_VALIDATED",
        "seed_order": "predeclared sequential; no cross-seed memory",
        "bootstrap_policy": (
            "Exactly cold_start_per_seed attempt intents; exclusions consume slots and stop. "
            "No valid bootstrap evidence means stop, not replacement or external warm start"
        ),
        "claim": "Prepared/frozen design is NOT an executed benchmark or target achievement",
        "stop_policy": (
            "Exclusions consume attempts and require inspection; no automatic paid retry, "
            "seed cherry-picking or success-based early stop"
        ),
        "regression": (
            "Use separately budgeted versioned replay of verified representative cases; "
            "not free replacements"
        ),
    }
    return {"manifest": manifest, "sha256": digest(manifest)}
