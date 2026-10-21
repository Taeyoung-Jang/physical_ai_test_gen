"""Independent latest-trajectory AFS/Random comparison; durable dispatch is reused unchanged.

Search feedback remains expanded-ten-v1. Both arms are scored by one frozen twelve-
family evaluator, with the original six-family view separately retained. No live calls
are made by planning, initialization, status or reporting.
"""

import json
import os
from html import escape
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from clear_path.search_domain import checked_domain
from failure_client.evaluation.failure_taxonomy import classify_record, profile_for_scene
from failure_client.evaluation.goal_run_reader import _hash_file, read_goal_run, read_json
from failure_client.evaluation.research_records import ComparisonDesign, RunInput, StrictRecord
from failure_client.evaluation.system_taxonomy import classify_system
from failure_client.evaluation.taxonomy_profiles import metric_options
from failure_client.methods.autonomous_feedback import SearchBudget
from failure_client.methods.behavior_feedback import uniform_scene
from failure_client.reporting.classification_explanation import (
    classification_explanation,
    saved_feedback_audit,
)
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.storage.research_store import ResearchStore
from llm_afs.behavior import digest

from .afs_autonomous import development_plan, stamp
from .discovery_evaluation import evaluation_fingerprint
from .independent_discovery import IndependentSeed
from .local_goal_adapter import atomic_json
from .research_protocol import PROJECT, CampaignConfig

MODE = "paired-trajectory-discovery-v1"
METHODS = ("afs", "random")
LIMITS = [
    "No external or cross-arm/seed history; controls bind settings only, never warm starts",
    "Paired bootstrap scenes are separately executed and charged to both arms",
    "All valid cold starts/repeats enter the fixed valid budget; exclusions consume attempts",
    "Exclusions or ambiguous requests STOP; explicit acknowledgement is not a paid request retry",
    "AFS search still uses ten-family feedback; common twelve-family scoring "
    "is NOT twelve-aware search",
    "Original six-family metrics remain separate; unsupported rules and "
    "unclassified failures remain",
    "Complete equal valid budgets are required for Gain; zero Random FDR yields no relative ratio",
    "Connection smoke and mock results never establish performance superiority "
    "or benchmark milestones",
    "No outcome-based early stop, seed selection, implicit simulation/token cap "
    "or standard/flex fallback",
    "Two runs in the same scene are separate episodes, not deterministic physics/model repeats",
]
RANDOM_LIMITS = [
    "Random-only descriptive environment exploration; no AFS comparison or Gain claim",
    "Predeclared seeds and full-domain independent uniform draws; no outcome-based selection",
    "Controls bind robot/settings only; no external history or free copied episodes",
    "All valid episodes count; exclusions consume attempts and STOP; no automatic replacement",
    "Zero AFS calls; robot action selection still uses the frozen GPT robot policy",
    "Fixed topology/object counts/bounds; not new venue generation or matched-change Random",
    "Marginal parameter bins are not joint environmental or failure-family coverage",
    "Common twelve-family and separate original-six scoring; unsupported remains unsupported",
    "No implicit token/simulation cap, tier fallback, automatic episode retry or budget reset",
]


class PairedDesign(StrictRecord):
    schema_version: Literal["paired-trajectory-design-v1"] = "paired-trajectory-design-v1"
    purpose: Literal["connection-smoke", "evaluation", "random-environment-sweep"] = (
        "connection-smoke"
    )
    methods: list[Literal["afs", "random"]] = Field(default_factory=lambda: list(METHODS))
    seeds: list[int] = Field(default_factory=lambda: [17], min_length=1, max_length=20)
    valid_per_arm: int = Field(default=3, ge=3, le=60)
    attempts_per_arm: int = Field(default=4, ge=3, le=72)
    afs_requests_per_seed: int = Field(default=2, ge=0, le=72)
    cold_start_per_arm: int = Field(default=2, ge=0)
    target_families_twelve: int = Field(default=4, ge=1, le=12)
    search: SearchBudget
    scene_domain: dict | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.scene_domain is not None:
            checked_domain(self.scene_domain)
        random_only = self.purpose == "random-environment-sweep"
        if random_only:
            if (
                self.methods != ["random"]
                or self.afs_requests_per_seed != 0
                or self.cold_start_per_arm != 0
            ):
                raise ValueError(
                    "Random-only sweep requires Random only, zero AFS and zero bootstrap"
                )
        elif (
            self.methods != list(METHODS)
            or self.afs_requests_per_seed < 1
            or self.cold_start_per_arm < 1
        ):
            raise ValueError("paired comparison requires both methods, AFS budget and cold starts")
        if len(set(self.seeds)) != len(self.seeds) or any(s < 0 for s in self.seeds):
            raise ValueError("distinct predeclared nonnegative seeds required")
        if not self.cold_start_per_arm < self.valid_per_arm <= self.attempts_per_arm:
            raise ValueError("cold start < valid target <= attempt cap required")
        required = {
            "selection_policy": "failure-branch-v3",
            "exploration_policy": "breadth-v1",
            "feedback_policy": "cause-review-v3",
            "pattern_feedback": "trajectory-v1",
            "anchor_policy": "failure-diversity-v4",
            "taxonomy_profile": "expanded-ten-v1",
            "reproposal_policy": "bounded-rejection-v1",
            "max_repeats": 0,
            "valid_rollout_target": self.valid_per_arm,
            "max_attempts": self.attempts_per_arm,
            # Shared legacy dispatch budget requires >=1. Random never reaches its
            # proposal branch; public manifest/caps and arm remaining requests are zero.
            "max_afs_requests": max(1, self.afs_requests_per_seed),
        }
        if any(getattr(self.search, key) != value for key, value in required.items()):
            raise ValueError(
                "paired design must bind the latest trajectory policy and matching budgets"
            )
        return self


def paired_fingerprint(config):
    value = evaluation_fingerprint(config)
    value["source_hashes"]["tools/run_paired_discovery.py"] = _hash_file(
        PROJECT / "tools/run_paired_discovery.py"
    )
    value["source_hashes"]["tools/run_random_environment.py"] = _hash_file(
        PROJECT / "tools/run_random_environment.py"
    )
    value["source_hashes"]["tools/run_navigation_comparison.sh"] = _hash_file(
        PROJECT / "tools/run_navigation_comparison.sh"
    )
    return value


def paired_plan(paths, design, *, fingerprint_fn=None):
    design = PairedDesign.model_validate(design.model_dump())
    locked = development_plan(
        paths, design.search, fingerprint_fn=fingerprint_fn or paired_fingerprint
    )
    original = locked["plan"]
    cfg = CampaignConfig.model_validate(original["target_config"])
    n = len(design.seeds)
    arm_count = n * len(design.methods)
    random_only = design.methods == ["random"]
    manifest = {
        "schema_version": MODE,
        "design": design.model_dump(),
        "robot_config": original["target_config"],
        "environment": locked["environment"],
        "reference_condition_id": original["condition_id"],
        "reference_geometry_id": original["geometry_id"],
        "execution_origin": original["execution_origin"],
        "control_provenance": [
            {k: r[k] for k in ("source", "artifact_hashes", "evidence_id")}
            for r in original["history"]
        ],
        "external_history_in_evaluation": [],
        "methods": design.methods,
        "method_assignment": "Random only; no proposer or AFS arm exists"
        if random_only
        else "separate arm ledger; only own seed and arm feed AFS",
        "execution_order": "predeclared sequential seeds and draw indices; no outcome selection"
        if random_only
        else "predeclared sequential seeds, least-attempted unfinished arm; AFS first on ties",
        "bootstrap": "none; all episodes are independent full-domain Random draws"
        if random_only
        else "paired-bootstrap-v1, same seed/index draws, two separately paid executions",
        "random_distribution": "independent uniform over each declared full-range scene axis; "
        "no novelty filter",
        "domain_axes": cfg.design()["axes"],
        "domain_id": digest({"schema": cfg.scene_schema, "axes": cfg.design()["axes"]}),
        "evaluators": {
            "primary": metric_options(cfg.scene_schema, "system-twelve-v1"),
            "original_six": metric_options(cfg.scene_schema),
        },
        "valid_total": arm_count * design.valid_per_arm,
        "attempt_cap_total": arm_count * design.attempts_per_arm,
        "robot_api_call_upper_bound": arm_count * design.attempts_per_arm * cfg.robot.max_calls,
        "afs_request_upper_bound": n * design.afs_requests_per_seed,
        "relative_gain_definition": "(FDR_AFS-FDR_Random)/FDR_Random; null if Random FDR=0",
        "limits": RANDOM_LIMITS if random_only else LIMITS,
    }
    if design.scene_domain is not None:
        axes = checked_domain(design.scene_domain, cfg.scene_schema)
        manifest.update(
            scene_domain=design.scene_domain,
            domain_axes=axes,
            domain_id=digest({"schema": cfg.scene_schema, "axes": axes}),
            random_distribution="independent uniform over every frozen bounded-domain axis; "
            "no geometry/outcome rejection, clipping or novelty filter",
            limits=[
                *manifest["limits"],
                "Bounded development-derived subdomain, not the original full-domain benchmark",
                "Subdomain results do not establish whole-project original-family coverage",
            ],
        )
    return {"manifest": manifest, "sha256": digest(manifest)}


def checked_manifest(wrapped):
    manifest = wrapped["manifest"]
    if wrapped.get("sha256") != digest(manifest) or manifest.get("schema_version") != MODE:
        raise ValueError("paired manifest digest or schema changed")
    design = PairedDesign.model_validate(manifest["design"])
    cfg = CampaignConfig.model_validate(manifest["robot_config"])
    domain = design.scene_domain
    axes = cfg.design()["axes"] if domain is None else checked_domain(domain, cfg.scene_schema)
    if (
        manifest.get("scene_domain") != domain
        or digest(manifest.get("domain_axes")) != digest(axes)
        or manifest.get("domain_id") != digest({"schema": cfg.scene_schema, "axes": axes})
    ):
        raise ValueError("frozen shared scene domain binding changed")
    n = len(design.seeds)
    arm_count = n * len(design.methods)
    expected = {
        "valid_total": arm_count * design.valid_per_arm,
        "attempt_cap_total": arm_count * design.attempts_per_arm,
        "robot_api_call_upper_bound": arm_count * design.attempts_per_arm * cfg.robot.max_calls,
        "afs_request_upper_bound": n * design.afs_requests_per_seed,
    }
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError("paired manifest budget totals changed")
    if manifest.get("external_history_in_evaluation") != [] or manifest.get("methods") != list(
        design.methods
    ):
        raise ValueError("paired manifest history/method policy changed")
    if manifest["execution_origin"] not in {"mock", "openai_api"}:
        raise ValueError("invalid execution origin")
    if digest(manifest["evaluators"]) != digest(
        {
            "primary": metric_options(cfg.scene_schema, "system-twelve-v1"),
            "original_six": metric_options(cfg.scene_schema),
        }
    ):
        raise ValueError("frozen evaluator registry changed")
    return manifest


class PairedArm(IndependentSeed):
    mode = MODE

    @classmethod
    def initialize(cls, root, wrapped, seed, method):
        manifest = checked_manifest(wrapped)
        design = PairedDesign.model_validate(manifest["design"])
        if seed not in design.seeds or method not in design.methods:
            raise ValueError("unplanned seed or method")
        plan = {
            "mode": MODE,
            "history": [],
            "seed": seed,
            "method": method,
            "cold_start_per_seed": design.cold_start_per_arm,
            "budget": design.search.model_dump(),
            "target_config": manifest["robot_config"],
            "condition_id": manifest["reference_condition_id"],
            "geometry_id": manifest["reference_geometry_id"],
            "execution_origin": manifest["execution_origin"],
            "robot_api_call_upper_bound": design.attempts_per_arm
            * manifest["robot_config"]["robot"]["max_calls"],
            "afs_request_upper_bound": design.afs_requests_per_seed if method == "afs" else 0,
            "manifest_sha256": wrapped["sha256"],
            "limits": manifest["limits"],
        }
        if design.scene_domain is not None:
            plan["scene_domain"] = design.scene_domain
        lock = {"plan": plan, "environment": manifest["environment"]}
        root = Path(root)
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "protocol.json", {"lock": lock, "lock_sha256": digest(lock)})
        ResearchStore(root).save(
            {
                "schema_version": MODE,
                "lock": lock,
                "lock_sha256": digest(lock),
                "status": "READY",
                "reason": None,
                "pending": None,
                "selected": None,
                "attempts": [],
                "proposals": [],
            },
            -1,
            "created",
        )

    def _selection(self):
        index = len(self.state["attempts"])
        cold = index < self.plan["cold_start_per_seed"]
        if cold or self.plan["method"] == "random":
            return {
                "stage": "cold_start" if cold else "discovery",
                "strategy": "paired_uniform_bootstrap" if cold else "independent_uniform_random",
                "axis": None,
                "parameters": uniform_scene(
                    self.plan["seed"],
                    "paired-bootstrap-v1" if cold else "paired-random-v1",
                    index,
                    schema=self.cfg.scene_schema,
                    domain=self.plan.get("scene_domain"),
                ),
                "evidence": {"source": "seeded uniform draw, not LLM proposal or fallback"},
                "scheduler": {"seed": self.plan["seed"], "index": index},
            }, None
        return super()._selection()

    def _breadth_summary(self, attempts, axes):
        return {} if self.plan["method"] == "random" else super()._breadth_summary(attempts, axes)

    def _proposal(self, ctx):
        if self.plan["method"] != "afs":
            raise ValueError("Random arm must never dispatch a proposer")
        return super()._proposal(ctx)

    def evaluation_records(self):
        return [
            r.model_copy(
                update={
                    "source": r.source.model_copy(
                        update={"method": self.plan["method"], "seed": self.plan["seed"]}
                    )
                }
            )
            for r in self._records()
        ]

    def summary(self):
        result = super().summary()
        result.update(method=self.plan["method"], limits=self.plan["limits"])
        result["selection_cost_scope"] = (
            "AFS requests only; Random selection makes zero model calls"
        )
        if self.plan["method"] == "random":
            result["afs_requests_remaining"] = 0
            result["breadth_cold_start_accounting"] = (
                "Uniform sampling; no AFS axis/group/form allocation"
            )
        return result


class PairedDiscovery:
    def __init__(self, root, *, runner=None, proposer=None, fingerprint_fn=None, on_event=None):
        self.root = Path(root).resolve()
        self.wrapped = read_json(self.root / "manifest.json")
        self.manifest = checked_manifest(self.wrapped)
        self.design = PairedDesign.model_validate(self.manifest["design"])
        if not (self.root / "campaign.sqlite3").is_file():
            raise ValueError("initialize a new paired campaign first")
        self.store = ResearchStore(self.root)
        self.kwargs = {
            "runner": runner,
            "proposer": proposer,
            "fingerprint_fn": fingerprint_fn or paired_fingerprint,
        }
        self.on_event = on_event
        state, _ = self.store.load()
        if state != {"mode": MODE, "manifest_sha256": self.wrapped["sha256"]}:
            raise ValueError("paired campaign ledger binding changed")

    @classmethod
    def create(cls, root, wrapped, *, fingerprint_fn=None):
        manifest = checked_manifest(wrapped)
        paths = [r["source"]["path"] for r in manifest["control_provenance"]]
        expected = paired_plan(
            paths, PairedDesign.model_validate(manifest["design"]), fingerprint_fn=fingerprint_fn
        )
        if digest(expected) != digest(wrapped):
            raise ValueError("paired preparation/control/environment changed; freeze a new plan")
        root = Path(root).resolve()
        if any(
            root.is_relative_to(Path(p).resolve()) or Path(p).resolve().is_relative_to(root)
            for p in paths
        ):
            raise ValueError("output overlaps control archives")
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "manifest.json", wrapped)
        ResearchStore(root).save(
            {"mode": MODE, "manifest_sha256": wrapped["sha256"]}, -1, "created"
        )
        for seed in manifest["design"]["seeds"]:
            for method in manifest["methods"]:
                PairedArm.initialize(root / "seeds" / str(seed) / method, wrapped, seed, method)
        return root

    def arm(self, seed, method):
        if seed not in self.design.seeds or method not in self.design.methods:
            raise ValueError("unplanned arm")
        kwargs = dict(self.kwargs)
        if self.on_event:
            kwargs["on_event"] = lambda event: self.on_event(
                {"seed": seed, "method": method, **event}
            )
        arm = PairedArm(self.root / "seeds" / str(seed) / method, **kwargs)
        expected = self.manifest
        p = arm.plan
        if (
            p["manifest_sha256"] != self.wrapped["sha256"]
            or p["seed"] != seed
            or p["method"] != method
            or p["budget"] != self.design.search.model_dump()
            or p["cold_start_per_seed"] != self.design.cold_start_per_arm
            or p["target_config"] != expected["robot_config"]
            or p["condition_id"] != expected["reference_condition_id"]
            or p["geometry_id"] != expected["reference_geometry_id"]
            or p["execution_origin"] != expected["execution_origin"]
            or arm.state["lock"]["environment"] != expected["environment"]
            or p.get("scene_domain") != self.design.scene_domain
        ):
            raise ValueError("paired arm configuration binding changed")
        if method == "random" and arm.state["proposals"]:
            raise ValueError("Random ledger contains AFS proposals")
        return arm

    def arms(self):
        return [
            self.arm(seed, method) for seed in self.design.seeds for method in self.design.methods
        ]

    def run(
        self,
        *,
        live=False,
        max_new_attempts=1,
        max_new_afs_requests=1,
        continue_after_exclusion=False,
    ):
        if not live:
            raise ValueError("explicit --live required")
        if any(type(v) is not int or v < 1 for v in (max_new_attempts, max_new_afs_requests)):
            raise ValueError("positive invocation limits required")
        launched = requested = 0
        acknowledged = False
        with self.store.exclusive():
            for control in self.manifest["control_provenance"]:
                record = read_goal_run(RunInput.model_validate(control["source"]))
                if (
                    record.status != "VALID"
                    or record.evidence_id != control["evidence_id"]
                    or record.artifact_hashes != control["artifact_hashes"]
                ):
                    raise ValueError("frozen control provenance changed")
            for arm in self.arms():
                arm._fresh()  # validate EVERY arm before the first paid dispatch
            while launched < max_new_attempts:
                arms = self.arms()
                blocked = next((a for a in arms if a.state["status"] == "NEEDS_ATTENTION"), None)
                stopped = next(
                    (
                        a
                        for a in arms
                        if a.state["status"] in {"TARGET_NOT_REACHED", "BUDGET_EXHAUSTED"}
                    ),
                    None,
                )
                if stopped is not None:
                    break
                if blocked is not None:
                    if blocked.state["pending"] is not None:
                        current = blocked  # collect saved evidence; no new paid dispatch
                    elif not continue_after_exclusion or acknowledged:
                        break
                    else:
                        current = blocked
                        acknowledged = True
                else:
                    current = None
                    for seed in self.design.seeds:
                        available = [
                            a
                            for a in arms
                            if a.plan["seed"] == seed
                            and a.state["status"] not in {"COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}
                        ]
                        if available:
                            current = min(
                                available,
                                key=lambda a: (
                                    len(a.state["attempts"]),
                                    METHODS.index(a.plan["method"]),
                                ),
                            )
                            break
                    if current is None:
                        break
                if current.plan["method"] == "afs" and requested >= max_new_afs_requests:
                    break
                before = (len(current.state["attempts"]), len(current.state["proposals"]))
                collecting = current.state["pending"] is not None
                result = current.run(
                    live=True,
                    max_new_attempts=0 if collecting else 1,
                    max_new_afs_requests=max(1, max_new_afs_requests - requested),
                    continue_after_exclusion=current is blocked and acknowledged,
                )
                delta = (
                    result["attempted"] - before[0],
                    result["afs_requests_attempted"] - before[1],
                )
                launched += delta[0]
                requested += delta[1]
                self.summary()  # reject cross-arm duplicate evidence BEFORE another dispatch
                if result["status"] == "NEEDS_ATTENTION" or delta == (0, 0):
                    break
        return self.summary()

    def summary(self):
        arms = self.arms()
        for arm in arms:
            arm._verify_evidence()
        raw = [r for arm in arms for r in arm.evaluation_records()]
        cfg = CampaignConfig.model_validate(self.manifest["robot_config"])
        comparison = (
            ComparisonDesign(
                domain_id=self.manifest["domain_id"],
                sampling_distribution=self.manifest["random_distribution"],
                condition_id=self.manifest["reference_condition_id"],
                valid_budget_per_seed=self.design.valid_per_arm,
                seeds=self.design.seeds,
            )
            if self.design.methods == list(METHODS)
            else None
        )
        profiles = {
            "system_twelve": (list(map(classify_system, raw)), "system-twelve-v1"),
            "original_six": (
                [classify_record(r, profile=profile_for_scene(cfg.scene_schema)) for r in raw],
                "scene-default",
            ),
        }
        metrics = {
            name: calculate_discovery_metrics(
                rows, comparison, **metric_options(cfg.scene_schema, profile)
            )
            for name, (rows, profile) in profiles.items()
        }
        explanations = {
            name: classification_explanation(
                rows, family_rules=metric_options(cfg.scene_schema, profile)["family_rules"]
            )
            for name, (rows, profile) in profiles.items()
        }
        if comparison is None:
            for view in metrics.values():
                view["comparison"] = {
                    "status": "not_requested_random_only",
                    "relative_gain": None,
                    "gain_target_observed": None,
                    "per_seed": [],
                }
        rows = [a.summary() for a in arms]
        complete = all(
            r["valid"] == self.design.valid_per_arm
            and r["status"] in {"COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}
            for r in rows
        )
        status = (
            "COMPLETE"
            if complete
            else next(
                (
                    r["status"]
                    for r in rows
                    if r["status"] not in {"READY", "COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}
                ),
                "READY",
            )
        )
        real = self.manifest["execution_origin"] == "openai_api"
        return {
            "campaign": str(self.root),
            "mode": MODE,
            "purpose": self.design.purpose,
            "status": status,
            "evaluation_complete": complete,
            "fixed_budget_observation_available": complete
            and real
            and self.design.purpose == "evaluation"
            and metrics["system_twelve"]["comparison"]["status"] in {"measured", "baseline_zero"},
            "statistical_superiority_established": False,
            "smoke_is_not_target_achievement": self.design.purpose == "connection-smoke",
            "manifest_sha256": self.wrapped["sha256"],
            "design": self.design.model_dump(),
            **(
                {
                    "scene_domain": self.design.scene_domain,
                    "domain_id": self.manifest["domain_id"],
                    "domain_geometry_audit": self.domain_geometry_audit(),
                }
                if self.design.scene_domain is not None
                else {}
            ),
            "arms": rows,
            "metrics": metrics,
            "classification_explanations": explanations,
            "comparison": metrics["system_twelve"]["comparison"],
            "new_attempts": sum(r["attempted"] for r in rows),
            "afs_requests_attempted": sum(r["afs_requests_attempted"] for r in rows),
            "robot_api_call_upper_bound": self.manifest["robot_api_call_upper_bound"],
            "afs_request_upper_bound": self.manifest["afs_request_upper_bound"],
            "external_history_in_evaluation": [],
            "environment_distribution": self.environment_distribution(arms),
            "sampling_scope": "Same scene topology/object counts and declared parameter bounds; "
            "uniform parameter sampling, not new venue generation or matched-change Random",
            "limits": self.manifest["limits"],
        }

    def random_schedule(self):
        """All scheduled draws, including attempt slots that may remain unused. No calls."""
        cfg = CampaignConfig.model_validate(self.manifest["robot_config"])
        return [
            {
                "seed": seed,
                "index": index,
                "parameters": uniform_scene(
                    seed,
                    "paired-bootstrap-v1"
                    if index < self.design.cold_start_per_arm
                    else "paired-random-v1",
                    index,
                    schema=cfg.scene_schema,
                    domain=self.design.scene_domain,
                ),
            }
            for seed in self.design.seeds
            for index in range(self.design.attempts_per_arm)
        ]

    def domain_geometry_audit(self):
        """Report predeclared draws, never reject/resample according to geometry or outcome."""
        from clear_path.fixture import initial_goal_relation

        cfg = CampaignConfig.model_validate(self.manifest["robot_config"])
        schedule = self.random_schedule()
        gaps = [
            initial_goal_relation(cfg.scene(r["parameters"]))["goal_to_box_distance_m"]
            for r in schedule
        ]
        return {
            "planned_random_slots_including_unused": len(schedule),
            "initial_goal_center_box_clearance_min_m": min(gaps),
            "initial_goal_center_box_clearance_over_0_4_m": sum(g > 0.4 for g in gaps),
            "rejected_or_resampled": 0,
            "claim": "Initial projected box geometry only; NOT complete path/physical feasibility, "
            "robot success probability or measured failures",
        }

    def environment_distribution(self, arms):
        """Marginal third-bin counts are descriptions, never joint/failure coverage."""
        axes = self.manifest["domain_axes"]
        planned = [r["parameters"] for r in self.random_schedule()]
        attempted = [
            a["candidate"]["parameters"]
            for arm in arms
            if arm.plan["method"] == "random"
            for a in arm.state["attempts"]
        ]

        def describe(rows):
            return {
                axis: {
                    "allowed": [lo, hi],
                    "minimum": min((r[axis] for r in rows), default=None),
                    "maximum": max((r[axis] for r in rows), default=None),
                    "third_bin_counts": [
                        sum(min(2, int(3 * (r[axis] - lo) / (hi - lo))) == i for r in rows)
                        for i in range(3)
                    ],
                }
                for axis, (lo, hi) in axes.items()
            }

        return {
            "planned_random_attempt_slots": len(planned),
            "random_attempt_intents": len(attempted),
            "planned": describe(planned),
            "attempted": describe(attempted),
            "limits": "Includes excluded intents; marginal parameter distribution is not "
            "joint scene coverage, physical difficulty, or failure-family coverage; "
            "independent uniform draws do not guarantee balanced bins",
        }

    def report(self):
        with self.store.exclusive():
            result = self.summary()
            output = self.root / "reports" / stamp()
            output.mkdir(parents=True, exist_ok=False)
            atomic_json(output / "summary.json", result)
            atomic_json(output / "design_manifest.json", self.wrapped)
            atomic_json(output / "planned_random_scenes.json", self.random_schedule())
            links = []
            audits = []
            for arm in self.arms():
                label = f"{arm.plan['seed']}_{arm.plan['method']}"
                atomic_json(output / f"{label}_attempts.json", arm.state["attempts"])
                atomic_json(output / f"{label}_proposals.json", arm.state["proposals"])
                atomic_json(output / f"{label}_ledger.json", arm.store.ledger())
                for proposal in arm.state["proposals"]:
                    folder = arm.root / "proposals" / proposal["id"]
                    if all((folder / name).is_file() for name in ("context.json", "request.json")):
                        try:
                            audit = saved_feedback_audit(
                                read_json(folder / "context.json"),
                                read_json(folder / "request.json"),
                                read_json(folder / "response.json")
                                if (folder / "response.json").is_file()
                                else None,
                            )
                        except (ValueError, TypeError, KeyError) as exc:
                            # Optional display inspection must not hide an invalid or
                            # incomplete proposal's original stopped-run evidence.
                            audit = {
                                "status": "NOT_VERIFIABLE",
                                "reason": type(exc).__name__,
                                "claim": "Not proof that feedback was absent; "
                                "no response repair/resend",
                            }
                        audits.append(
                            {
                                "seed": arm.plan["seed"],
                                "method": arm.plan["method"],
                                "proposal_id": proposal["id"],
                                "audit": audit,
                            }
                        )
                for attempt in arm.state["attempts"]:
                    folder = arm.root / "attempts" / attempt["id"] / "rollout"
                    for name in ("report.html", "rollout.mp4"):
                        if (folder / name).is_file():
                            href = escape(os.path.relpath(folder / name, output), quote=True)
                            links.append(
                                f'<li><a href="{href}">{label}/{attempt["id"]}/{name}</a></li>'
                            )
            atomic_json(output / "afs_feedback_audit.json", audits)
            explanation = result["classification_explanations"]["system_twelve"]
            rows = []
            for method, group in explanation["pooled_by_method"].items():
                counts = group["counts"]
                rows.append(
                    "<tr><td>"
                    + escape(method)
                    + "</td>"
                    + "".join(f"<td>{counts[key]}</td>" for key in explanation["labels"])
                    + "</tr>"
                )
            headings = "".join(
                f"<th>{escape(label)}</th>" for label in explanation["labels"].values()
            )
            display = (
                "<h2>실패 분류 설명 — 12종 기준</h2><p>FAIL 에피소드별 집계입니다. "
                "복합 징후를 새 실패 유형으로 추가하거나 기존 발견 지표를 바꾸지 않습니다.</p>"
                '<table border="1"><tr><th>방법</th>'
                + headings
                + "</tr>"
                + "".join(rows)
                + "</table>"
                '<p><a href="afs_feedback_audit.json">저장된 AFS 피드백 전달 확인</a></p>'
            )
            title = (
                "Random 환경 탐색 — AFS 비교/Gain 아님"
                if self.design.methods == ["random"]
                else (
                    "AFS/Random 연결 검증 — 성능 달성 증거 아님"
                    if self.design.purpose == "connection-smoke"
                    else "고정 예산 AFS/Random 비교"
                )
            )
            (output / "report.html").write_text(
                '<!doctype html><meta charset="utf-8"><h1>'
                + title
                + "</h1>"
                + display
                + "<ul>"
                + "".join(links)
                + "</ul><pre>"
                + escape(json.dumps(result, ensure_ascii=False, indent=2))
                + "</pre>"
            )
            atomic_json(
                output / "manifest.json",
                {
                    "artifacts": [
                        {"path": str(p.relative_to(output)), "sha256": _hash_file(p)}
                        for p in sorted(output.iterdir())
                        if p.is_file()
                    ]
                },
            )
            return output / "report.html"
