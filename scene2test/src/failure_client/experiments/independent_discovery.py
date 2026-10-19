"""Seed-isolated AFS evaluation, reusing durable at-most-once rollout dispatch.

Controls bind executable settings only. Neither their outcomes nor their scenes
enter evaluation memory. Random-relative Gain is deliberately not evaluated here.
"""

import json
import os
from html import escape
from pathlib import Path

from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.evaluation.taxonomy_profiles import metric_options
from failure_client.methods.behavior_feedback import uniform_scene
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.storage.research_store import ResearchStore
from llm_afs.behavior import digest

from .afs_autonomous import AutonomousAFS, stamp
from .discovery_evaluation import EvaluationDesign, evaluation_fingerprint
from .local_goal_adapter import atomic_json
from .research_protocol import CampaignConfig

MODE = "independent-afs-discovery-v1"
LIMITS = [
    "No external or cross-seed search history; all cold starts consume the frozen budget",
    "FDR and distinct measured primary families use all new valid episodes, including cold starts",
    "Exclusions consume attempts and stop for inspection; no automatic replacement or paid retry",
    "No metric-success early stop, seed selection, or Random-relative Gain claim",
    "Operational family association is not causal proof; unsupported rules remain unsupported",
    "No implicit simulation or client output-token ceiling; partial usage is not zero",
]


def checked_manifest(wrapped, *, schema_version="joint-discovery-evaluation-manifest-v2"):
    manifest = wrapped["manifest"]
    if wrapped.get("sha256") != digest(manifest):
        raise ValueError("evaluation manifest hash mismatch")
    if manifest.get("schema_version") != schema_version:
        raise ValueError("new executable evaluation manifest required; re-freeze the design")
    if manifest.get("external_history_in_evaluation") != []:
        raise ValueError("external evaluation history is forbidden")
    design = EvaluationDesign.model_validate(manifest["design"])
    cfg = CampaignConfig.model_validate(manifest["robot_config"])
    n = len(design.seeds)
    totals = {
        "valid_total": n * design.valid_per_seed,
        "attempt_cap_total": n * design.attempts_per_seed,
        "robot_api_call_upper_bound": n * design.attempts_per_seed * cfg.robot.max_calls,
        "afs_request_upper_bound": n * design.afs_requests_per_seed,
    }
    if any(manifest.get(k) != v for k, v in totals.items()):
        raise ValueError("manifest totals differ from predeclared evaluation budgets")
    if manifest["execution_origin"] not in {"openai_api", "mock"}:
        raise ValueError("unsupported evaluation execution origin")
    return manifest


class IndependentSeed(AutonomousAFS):
    mode = MODE
    request_policy = "independent_evaluation_endpoint"

    @classmethod
    def initialize(cls, root, wrapped, seed):
        manifest = checked_manifest(wrapped)
        design = EvaluationDesign.model_validate(manifest["design"])
        if seed not in design.seeds:
            raise ValueError("seed is not predeclared")
        plan = {
            "mode": cls.mode,
            "history": [],
            "seed": seed,
            "cold_start_per_seed": design.cold_start_per_seed,
            "budget": design.search.model_dump(),
            "target_config": manifest["robot_config"],
            "condition_id": manifest["reference_condition_id"],
            "geometry_id": manifest["reference_geometry_id"],
            "execution_origin": manifest["execution_origin"],
            "robot_api_call_upper_bound": design.attempts_per_seed
            * manifest["robot_config"]["robot"]["max_calls"],
            "afs_request_upper_bound": design.afs_requests_per_seed,
            "manifest_sha256": wrapped["sha256"],
            "limits": LIMITS,
        }
        lock = {"plan": plan, "environment": manifest["environment"]}
        root = Path(root)
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "protocol.json", {"lock": lock, "lock_sha256": digest(lock)})
        ResearchStore(root).save(
            {
                "schema_version": cls.mode,
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

    def __init__(self, root, **kwargs):
        super().__init__(root, **{"fingerprint_fn": evaluation_fingerprint, **kwargs})
        if self.plan["history"] or self.state["lock"].get("recovery_sha256"):
            raise ValueError("independent seed contains external history")

    def _selection(self):
        index = len(self.state["attempts"])
        if index < self.plan["cold_start_per_seed"]:
            return {
                "stage": "cold_start",
                "strategy": "predeclared_uniform_cold_start",
                "axis": None,
                "parameters": uniform_scene(
                    self.plan["seed"],
                    "independent-cold-start-v1",
                    index,
                    schema=self.cfg.scene_schema,
                ),
                "evidence": {"source": "predeclared uniform bootstrap, not AFS fallback"},
                "scheduler": {"seed": self.plan["seed"], "cold_start_index": index},
            }, None
        if not self._memory()["cases"]:
            return None, None
        try:
            candidate, ctx = super()._selection()
        except ValueError as exc:
            if str(exc) == "no eligible branch: an observed PASS control may be required":
                return None, None
            raise
        if ctx is not None:
            ctx["development_search"].update(mode=self.mode, external_history=False)
            ctx["failure_objective"]["scope"] = (
                "Only this seed's newly executed episodes; all valid bootstrap and search "
                "episodes belong to the evaluation denominator"
            )
        return candidate, ctx

    def _breadth_summary(self, attempts, axes):
        result = super()._breadth_summary(
            [a for a in attempts if a["candidate"]["stage"] != "cold_start"], axes
        )
        if "exploration_allocation" in result:
            from failure_client.methods.autonomous_feedback import accounting
            from failure_client.methods.breadth_policy import allocation

            result["exploration_allocation"].update(
                allocation(attempts, accounting(attempts, axes, self.budget)["selectable_axes"])
            )
        return result

    def _selection_stop_reason(self, ctx):
        if ctx is None:
            if not self._memory()["cases"]:
                return "no_valid_cold_start_evidence"
            from failure_client.methods.autonomous_feedback import accounting

            if accounting(self.state["attempts"], self.cfg.design()["axes"], self.budget)[
                "selectable_axes"
            ]:
                return "no_eligible_observed_anchor"
        return super()._selection_stop_reason(ctx)

    def evaluation_records(self):
        return [
            r.model_copy(
                update={
                    "source": r.source.model_copy(
                        update={"method": "afs", "seed": self.plan["seed"]}
                    )
                }
            )
            for r in self._records()
        ]

    def summary(self):
        result = super().summary()
        result.pop("inherited_history_costs")
        result.pop("inherited_afs_selection_costs")
        result.update(
            seed=self.plan["seed"],
            external_history_in_evaluation=[],
            limits=LIMITS,
            new_only_discovery_metrics=calculate_discovery_metrics(
                self.evaluation_records(),
                **metric_options(self.cfg.scene_schema, self.budget.taxonomy_profile),
            ),
        )
        result["breadth_cold_start_accounting"] = (
            "Cold starts count in total attempts and the form-cycle index; no single-axis quota "
            "is charged because no anchor parameter was changed"
        )
        return result


class DiscoveryEvaluation:
    mode = MODE
    seed_type = IndependentSeed
    check_manifest = staticmethod(checked_manifest)

    def __init__(self, root, *, runner=None, proposer=None, fingerprint_fn=None, on_event=None):
        self.root = Path(root).resolve()
        self.wrapped = read_json(self.root / "manifest.json")
        self.manifest = self.check_manifest(self.wrapped)
        self.design = EvaluationDesign.model_validate(self.manifest["design"])
        self.kwargs = dict(
            runner=runner,
            proposer=proposer,
            fingerprint_fn=fingerprint_fn or evaluation_fingerprint,
            on_event=on_event,
        )
        if not (self.root / "campaign.sqlite3").is_file():
            raise ValueError("initialize a NEW evaluation campaign before status or execution")
        self.store = ResearchStore(self.root)
        state, _ = self.store.load()
        if state != {"manifest_sha256": self.wrapped["sha256"], "mode": self.mode}:
            raise ValueError("campaign manifest differs from initialized ledger")

    @classmethod
    def create(cls, root, wrapped, *, fingerprint_fn=None):
        manifest = cls.check_manifest(wrapped)
        cfg = CampaignConfig.model_validate(manifest["robot_config"])
        if (fingerprint_fn or evaluation_fingerprint)(cfg) != manifest["environment"]:
            raise ValueError("frozen evaluation source/resources/runtime changed; re-freeze")
        root = Path(root).resolve()
        for row in manifest["control_provenance"]:
            source = Path(row["source"]["path"]).resolve()
            if root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError("evaluation output overlaps control archives")
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "manifest.json", wrapped)
        for seed in manifest["design"]["seeds"]:
            cls.seed_type.initialize(root / "seeds" / str(seed), wrapped, seed)
        ResearchStore(root).save(
            {"manifest_sha256": wrapped["sha256"], "mode": cls.mode}, -1, "created"
        )
        return root

    def seed(self, value):
        kwargs = dict(self.kwargs)
        callback = kwargs.get("on_event")
        if callback:
            kwargs["on_event"] = lambda event: callback({"seed": value, **event})
        engine = self.seed_type(self.root / "seeds" / str(value), **kwargs)
        p, m = engine.plan, self.manifest
        if (
            p["manifest_sha256"] != self.wrapped["sha256"]
            or p["seed"] != value
            or p["budget"] != self.design.search.model_dump()
            or p["cold_start_per_seed"] != self.design.cold_start_per_seed
            or p["target_config"] != m["robot_config"]
            or p["condition_id"] != m["reference_condition_id"]
            or p["geometry_id"] != m["reference_geometry_id"]
            or p["execution_origin"] != m["execution_origin"]
            or engine.state["lock"]["environment"] != m["environment"]
        ):
            raise ValueError("seed manifest binding changed")
        return engine

    def run(
        self,
        *,
        live=False,
        max_new_attempts=None,
        continue_after_exclusion=False,
        max_new_afs_requests=None,
    ):
        if not live:
            raise ValueError("execution requires explicit --live")
        if max_new_attempts is not None and (
            type(max_new_attempts) is not int or max_new_attempts < 1
        ):
            raise ValueError("positive invocation attempt limit required")
        launched = 0
        requested = 0
        if max_new_afs_requests is not None and (
            type(max_new_afs_requests) is not int or max_new_afs_requests < 1
        ):
            raise ValueError("positive invocation AFS request limit required")
        with self.store.exclusive():
            # Validate every seed before spending on the first one.
            for value in self.design.seeds:
                self.seed(value)._fresh()
            for value in self.design.seeds:
                engine = self.seed(value)
                engine._fresh()
                if engine.state["status"] in {"COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}:
                    continue
                before = len(engine.state["attempts"])
                before_requests = len(engine.state["proposals"])
                result = engine.run(
                    live=True,
                    max_new_attempts=None
                    if max_new_attempts is None
                    else max_new_attempts - launched,
                    continue_after_exclusion=continue_after_exclusion,
                    max_new_afs_requests=None
                    if max_new_afs_requests is None
                    else max_new_afs_requests - requested,
                )
                launched += result["attempted"] - before
                requested += result["afs_requests_attempted"] - before_requests
                if result["status"] not in {"COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}:
                    break
                if max_new_attempts is not None and launched >= max_new_attempts:
                    break
                if max_new_afs_requests is not None and requested >= max_new_afs_requests:
                    break
        return self.summary()

    def summary(self):
        engines = [self.seed(s) for s in self.design.seeds]
        for engine in engines:
            engine._verify_evidence()
        seeds = [e.summary() for e in engines]
        terminal = {"COMPLETE", "COMPLETE_WITH_EXCLUSIONS"}
        status = (
            "COMPLETE"
            if all(s["status"] in terminal for s in seeds)
            else next(
                (
                    s["status"]
                    for s in seeds
                    if s["status"] != "READY" and s["status"] not in terminal
                ),
                "READY",
            )
        )
        records = [r for e in engines for r in e.evaluation_records()]
        metrics = calculate_discovery_metrics(
            records,
            **metric_options(engines[0].cfg.scene_schema, self.design.search.taxonomy_profile),
        )
        for group in metrics["groups"]:
            group.update(
                valid_budget=self.design.valid_per_seed,
                budget_status="complete"
                if group["valid_rollouts"] == self.design.valid_per_seed
                else "incomplete",
            )
        pooled = metrics["pooled_by_method"].get("afs", {})
        count = pooled.get("discovered_family_count")
        observed = (pooled.get("failure_discovery_rate") or 0) >= 0.3 and (
            count is not None and count >= 4
        )
        return {
            "campaign": str(self.root),
            "mode": self.mode,
            "status": status,
            "manifest_sha256": self.wrapped["sha256"],
            "design": self.design.model_dump(),
            "seeds": seeds,
            "discovery_metrics": metrics,
            "evaluation_complete": status == "COMPLETE",
            "joint_target_observed": observed,
            "joint_target_at_complete_budget": observed if status == "COMPLETE" else None,
            "target_scope": (
                "Across the full predeclared test set, not four labels in one episode; "
                "interim observations are not completed-evaluation achievement"
            ),
            "robot_api_call_upper_bound": self.manifest["robot_api_call_upper_bound"],
            "afs_request_upper_bound": self.manifest["afs_request_upper_bound"],
            "gain_phase": "DEFERRED_SEPARATE_RANDOM_COMPARISON",
            "limits": LIMITS,
        }

    def report(self):
        with self.store.exclusive():
            summary = self.summary()
            output = self.root / "reports" / stamp()
            output.mkdir(parents=True, exist_ok=False)
            atomic_json(output / "summary.json", summary)
            atomic_json(output / "manifest.json", self.wrapped)
            links = []
            for value in self.design.seeds:
                engine = self.seed(value)
                atomic_json(output / f"seed_{value}_attempts.json", engine.state["attempts"])
                atomic_json(output / f"seed_{value}_proposals.json", engine.state["proposals"])
                atomic_json(output / f"seed_{value}_ledger.json", engine.store.ledger())
                for attempt in engine.state["attempts"]:
                    aid = attempt["id"]
                    episode_root = Path(
                        attempt.get("episode", {})
                        .get("source", {})
                        .get("path", str(engine.root / "attempts" / aid / "rollout"))
                    )
                    for filename in ("report.html", "rollout.mp4"):
                        if (episode_root / filename).is_file():
                            href = escape(
                                os.path.relpath(episode_root / filename, output), quote=True
                            )
                            links.append(f'<li><a href="{href}">{value}/{aid}/{filename}</a></li>')
            (output / "report.html").write_text(
                '<!doctype html><meta charset="utf-8"><title>AFS search report</title>'
                + (
                    "<h1>독립 AFS 평가</h1>"
                    if self.mode == MODE
                    else "<h1>운영자 개입 개발 연속 실행</h1>"
                )
                + "<p>초기 실행 포함, seed별 이력 격리. "
                "Random 비교는 별도입니다.</p><ul>"
                + "".join(links)
                + "</ul><pre>"
                + escape(json.dumps(summary, ensure_ascii=False, indent=2))
                + "</pre>",
                encoding="utf-8",
            )
            atomic_json(
                output / "artifacts.json",
                {
                    "artifacts": [
                        {"path": str(p.relative_to(output)), "sha256": _hash_file(p)}
                        for p in sorted(output.rglob("*"))
                        if p.is_file()
                    ]
                },
            )
            return output / "report.html"
