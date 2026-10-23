"""Externally seeded, bounded development AFS. Never an AFS/Random benchmark.

Durable intents provide at-most-once dispatch, not an exactly-once remote service.
Ambiguous calls are never resent; saved evidence can be collected on resume.
"""

import json
import os
import time
from copy import deepcopy
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from failure_client.archive.regression_cases import (
    _scene_parameters,
    build_failure_memory,
    export_failure_memory,
)
from failure_client.evaluation.behavior_measures import verify_episode_files
from failure_client.evaluation.goal_run_reader import (
    _constant,
    _hash_file,
    _pairs,
    read_goal_run,
    read_json,
)
from failure_client.evaluation.research_records import EpisodeRecord, RunInput
from failure_client.evaluation.taxonomy_profiles import classify_for_search, metric_options
from failure_client.methods.autonomous_feedback import (
    SearchBudget,
    accounting,
    selected_probe,
    selection,
)
from failure_client.methods.behavior_feedback import NoEligibleEndpoint
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.reporting.search_diagnostics import experiment_reviews, search_diagnostics
from failure_client.storage.research_store import ResearchStore
from llm_afs import provider
from llm_afs.behavior import digest
from llm_afs.behavior_request import request
from robot_vlm.debug_log import clean, exception_detail

from .afs_contrast import evidence
from .behavior_regression import replay_plan
from .local_goal_adapter import LocalGoalRunner, atomic_json
from .research_protocol import PROJECT, CampaignConfig, environment_fingerprint

MODE = "autonomous-development-v1"
LIMITS = [
    "Reviewed external history; development search, NOT an AFS/Random comparison or Gain estimate",
    "Only scene parameters change; robot, goal, policy budget and completion stay fixed",
    "Axis diversity is not failure-family coverage; hypotheses and brackets are not causal proofs",
    "All intents, repeats and exclusions consume the frozen budget; no automatic paid retry",
    "Unknown/partial usage is not zero; inherited and new costs remain separate",
    "MP4 only, no GIF, default output-token ceiling or implicit simulation time cap",
]


def stamp():
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")


def proposal_request_digest(body):
    """Compare the whole request, parsing only its declared JSON text payload.

    Retain list order and every model/schema/instruction/transport value. DB sorting
    can change dict insertion order inside JSON strings without changing their meaning.
    Originals remain untouched; malformed/duplicate/nonfinite JSON is rejected.
    """
    normalized = deepcopy(body)
    for message in normalized["input"]:
        if not isinstance(message.get("content"), str):
            raise ValueError("expected a JSON text proposal request")
        message["content"] = json.loads(
            message["content"], object_pairs_hook=_pairs, parse_constant=_constant
        )
    return digest(normalized)


def fingerprint(config):
    env = environment_fingerprint(config)
    env["source_hashes"]["tools/run_afs_autonomous.py"] = _hash_file(
        PROJECT / "tools/run_afs_autonomous.py"
    )
    return env


def verify_history(plan, env):
    for row in plan["history"]:
        record = EpisodeRecord.model_validate(row)
        verify_episode_files(record)
        p = read_json(Path(record.source.path) / "protocol.json")
        if (
            not p["source_hashes"]
            or not set(p["source_hashes"].values()) <= set(env["source_hashes"].values())
            or any(env["robot_resources"].get(k) != v for k, v in p["robot_resources"].items())
            or any(
                env["runtime_versions"].get(k) != v
                for k, v in p.get("runtime_versions", {}).items()
            )
        ):
            raise ValueError("reviewed robot code/resources/runtime changed; new control required")


def development_plan(paths, budget=None, *, fingerprint_fn=None):
    """Read-only real-archive preflight; no renderer, API, database or scene launch."""
    if not 1 <= len(paths) <= 8:
        raise ValueError("supply 1..8 reviewed same-condition archives in observation order")
    budget = budget or SearchBudget()
    memory = evidence(paths)
    if memory["duplicates"]:
        raise ValueError("duplicate history archives are not independent observations")
    replay = replay_plan(paths, repeats=1)
    cfg = replay["cases"][0]["target_config"]
    if any(c["target_config"] != cfg for c in replay["cases"]):
        raise ValueError("reviewed history must use the same executable robot settings")
    # Reuse only the local runner's scene/robot adapter. Benchmark arm budgets,
    # strategy slots and its default AFS model have no meaning in this session.
    cfg = {"scene_schema": cfg["scene_schema"], "robot": cfg["robot"]}
    rows = [e["record"] for e in memory["episodes"].values()]
    if budget.selection_policy in {"discovery-v1", "failure-directed-v2", "failure-branch-v3"}:
        rows = [
            classify_for_search(
                EpisodeRecord.model_validate(r),
                cfg["scene_schema"],
                budget.taxonomy_profile,
            ).model_dump()
            for r in rows
        ]
    if len({r["policy_origin"] for r in rows}) != 1:
        raise ValueError("mixed mock/live origins")
    plan = {
        "mode": MODE,
        "history": rows,
        "budget": budget.model_dump(),
        "target_config": cfg,
        "condition_id": rows[0]["condition_id"],
        "geometry_id": memory["cases"][0]["geometry_id"],
        "execution_origin": rows[0]["policy_origin"],
        "robot_api_call_upper_bound": budget.max_attempts * cfg["robot"]["max_calls"],
        "afs_request_upper_bound": budget.max_afs_requests,
        "limits": LIMITS,
    }
    env = (fingerprint_fn or fingerprint)(CampaignConfig.model_validate(cfg))
    verify_history(plan, env)
    return {"plan": plan, "environment": env}


def costs(records, attempted):
    result = {}
    for field in ("observed_input_tokens", "observed_output_tokens", "robot_api_calls"):
        values = [r[field] for r in records if r.get(field) is not None]
        result[field] = {
            "observed": sum(values) if values else None,
            "missing_attempts": attempted - len(values),
        }
    audits = [r["usage_audit"] for r in records if r.get("usage_audit")]
    result["calls_missing_usage_observed"] = (
        sum(a["calls_missing_usage"] for a in audits) if audits else None
    )
    result["attempts_without_usage_audit"] = attempted - len(audits)
    return result


def ensure_not_running(directory):
    if (directory / "receipt.json").exists():
        return
    if (directory / "process.json").exists():
        pid = read_json(directory / "process.json")["pid"]
        if type(pid) is not int or pid <= 0:
            raise ValueError("invalid saved process id")
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        raise RuntimeError("saved robot process may still be active; no resend or collection")


class AutonomousAFS:
    mode = MODE
    request_policy = "autonomous_development_endpoint"

    def __init__(self, root, *, runner=None, proposer=None, fingerprint_fn=None, on_event=None):
        self.root = Path(root).resolve()
        if not (self.root / "protocol.json").is_file():
            raise ValueError("initialize an autonomous development session first")
        protocol = read_json(self.root / "protocol.json")
        if protocol.get("lock", {}).get("plan", {}).get("mode") != self.mode or protocol.get(
            "lock_sha256"
        ) != digest(protocol.get("lock")):
            # Reject old suites before opening (or creating tables in) their DB.
            raise ValueError("not an intact autonomous session protocol")
        self.store = ResearchStore(self.root)
        self.runner = runner or LocalGoalRunner()
        self.proposer = proposer or provider.call
        self.fingerprint = fingerprint_fn or fingerprint
        self.on_event = on_event
        self.state, self.revision = self.store.load()
        self._verify_lock()

    @classmethod
    def create(cls, root, paths, budget=None, *, fingerprint_fn=None):
        lock = development_plan(paths, budget, fingerprint_fn=fingerprint_fn)
        root = Path(root).resolve()
        for row in lock["plan"]["history"]:
            source = Path(row["source"]["path"]).resolve()
            if root.is_relative_to(source) or source.is_relative_to(root):
                raise ValueError("session output must be separate from all source archives")
        root.mkdir(parents=True, exist_ok=False)
        atomic_json(root / "protocol.json", {"lock": lock, "lock_sha256": digest(lock)})
        state = {
            "schema_version": MODE,
            "lock": lock,
            "lock_sha256": digest(lock),
            "status": "READY",
            "reason": None,
            "pending": None,
            "selected": None,
            "attempts": [],
            "proposals": [],
        }
        ResearchStore(root).save(state, -1, "created")
        return root

    @property
    def plan(self):
        return self.state["lock"]["plan"]

    @property
    def budget(self):
        return SearchBudget.model_validate(self.plan["budget"])

    @property
    def cfg(self):
        return CampaignConfig.model_validate(self.plan["target_config"])

    def _save(self, event, detail=None):
        self.revision = self.store.save(self.state, self.revision, event, detail)
        if self.on_event:
            self.on_event({"utc": stamp(), "event": event, "detail": detail or {}})

    def _verify_lock(self):
        expected = {"lock": self.state["lock"], "lock_sha256": digest(self.state["lock"])}
        if (
            self.state.get("schema_version") != self.mode
            or self.state["lock_sha256"] != expected["lock_sha256"]
            or read_json(self.root / "protocol.json") != expected
        ):
            raise ValueError("frozen autonomous session protocol mismatch")
        if (
            self.state["lock"].get("recovery_sha256")
            and digest(read_json(self.root / "recovery.json"))
            != self.state["lock"]["recovery_sha256"]
        ):
            raise ValueError("point recovery audit mismatch")
        if self.state["lock"].get("recovery_sha256"):
            audit = read_json(self.root / "recovery.json")
            if audit.get("schema_version") in {
                "numeric-candidate-recovery-v1",
                "anchor-behavior-ref-recovery-v1",
            }:
                snapshots = audit.get("source_snapshot_artifacts", {})
                if set(snapshots) != {
                    "source_state.json",
                    "source_ledger.json",
                    "source_protocol.json",
                }:
                    raise ValueError("numeric recovery source snapshot inventory mismatch")
                if any(_hash_file(self.root / name) != sha for name, sha in snapshots.items()):
                    raise ValueError("numeric recovery source snapshot changed")

    def _proposal_raw(self, row):
        directory = self.root / "proposals" / row["id"]
        raw = provider.extract_proposal(read_json(directory / "response.json"))
        if row.get("recovery"):
            if not self.state["lock"].get("recovery_sha256"):
                raise ValueError("unbound proposal recovery")
            audit = read_json(self.root / "recovery.json")
            fixed = read_json(directory / "normalized_proposal.json")
            if row["recovery"] == "anchor_behavior_refs":
                from .anchor_ref_recovery import normalize_anchor_refs

                normalized = normalize_anchor_refs(raw, read_json(directory / "context.json"))
            else:
                from .point_recovery import normalize_equal_ranges

                normalized = normalize_equal_ranges(raw)
            if (
                normalized != fixed
                or digest(fixed) != audit["normalized_proposal_sha256"]
                or any(row["artifacts"].get(k) != v for k, v in audit["original_artifacts"].items())
            ):
                raise ValueError("recovered proposal differs from original response")
            return fixed
        return raw

    def _verify_evidence(self):
        for row in self.plan["history"]:
            verify_episode_files(EpisodeRecord.model_validate(row))
        for a in self.state["attempts"]:
            raw = a.get("raw_episode", {})
            if raw.get("status") in {"VALID", "INCONCLUSIVE"} and raw.get("artifact_hashes"):
                verify_episode_files(EpisodeRecord.model_validate(raw))
        for p in self.state["proposals"]:
            for name, sha in p.get("artifacts", {}).items():
                if _hash_file(self.root / "proposals" / p["id"] / name) != sha:
                    raise ValueError("saved selection evidence changed")

    def _fresh(self):
        self._verify_lock()
        self._verify_evidence()
        env = self.fingerprint(self.cfg)
        if env != self.state["lock"]["environment"]:
            raise ValueError("frozen source/resources/runtime changed; session cannot resume")
        verify_history(self.plan, env)

    def _records(self):
        return [EpisodeRecord.model_validate(r) for r in self.plan["history"]] + [
            EpisodeRecord.model_validate(a["episode"])
            for a in self.state["attempts"]
            if "episode" in a
        ]

    def _memory(self):
        return build_failure_memory(self._records())

    def _selection(self):
        candidate, ctx = selection(
            self._memory(),
            self.state["attempts"],
            self.budget,
            self.cfg.scene_schema,
            scene_domain=self.plan.get("scene_domain"),
        )
        if ctx is not None and self.budget.reproposal_policy == "bounded-rejection-v1":
            # Only finalized rejections enter the NEXT context. The pending response
            # and validated candidate must not change their own context on resume.
            dispatched = {a["candidate"].get("proposal_id") for a in self.state["attempts"]}
            ctx["proposal_feedback"] = {
                "policy": self.budget.reproposal_policy,
                "remaining_requests": self.budget.max_afs_requests
                - sum("rejection" in p or p["id"] in dispatched for p in self.state["proposals"]),
                "rejected_proposals": [
                    {"proposal_id": p["id"], **p["rejection"]}
                    for p in self.state["proposals"]
                    if "rejection" in p
                ][-4:],
            }
        return candidate, ctx

    def _selection_stop_reason(self, ctx):
        return "no_selectable_axis" if ctx is None else "afs_request_budget"

    def _proposal(self, ctx):
        directory = self.root / "proposals" / f"proposal_{len(self.state['proposals']):05d}"
        body = request(
            ctx,
            self.budget.afs_model,
            selection_policy=self.request_policy,
            service_tier=self.budget.afs_service_tier,
            api_provider=self.budget.afs_api_provider,
        )
        directory.mkdir(parents=True, exist_ok=False)
        atomic_json(directory / "context.json", ctx)
        atomic_json(directory / "request.json", body)
        row = {
            "id": directory.name,
            "artifacts": {n: _hash_file(directory / n) for n in ("context.json", "request.json")},
        }
        self.state["proposals"].append(row)
        self.state["pending"] = {"kind": "proposal", "index": len(self.state["proposals"]) - 1}
        self._save("proposal_intent", {"id": row["id"], "context_sha256": digest(ctx)})
        started = time.monotonic()
        try:
            response = self.proposer(body, timeout=self.budget.afs_timeout_s)
            atomic_json(directory / "response.json", response)
        finally:
            # A hard process loss can leave this unknown; never replace it with zero.
            row["wall_s"] = time.monotonic() - started
            self._save("proposal_dispatch_finished", {"id": row["id"]})
        self._finish_proposal(row)

    def _finish_proposal(self, row):
        directory = self.root / "proposals" / row["id"]
        path = directory / "response.json"
        if not path.is_file():
            raise RuntimeError("ambiguous proposal intent without saved response; never resend")
        response = read_json(path)
        row.update(
            usage=response.get("usage"),
            api_provider=self.budget.afs_api_provider,
            returned_api_provider=response.get("api_provider", "openai"),
            routed_provider=response.get("routed_provider"),
            returned_model=response.get("model"),
            requested_service_tier=self.budget.afs_service_tier,
            returned_service_tier=response.get("service_tier"),
        )
        row["artifacts"]["response.json"] = _hash_file(path)
        self._save("proposal_response_collected", {"id": row["id"]})
        if response.get("api_provider", "openai") != self.budget.afs_api_provider:
            raise ValueError("AFS response provider differs from frozen request; never resend")
        if (
            self.budget.afs_service_tier is not None
            and response.get("service_tier") != self.budget.afs_service_tier
        ):
            raise ValueError(
                "AFS response service_tier does not confirm requested tier; never resend"
            )
        self._fresh()
        candidate, ctx = self._selection()
        if (
            candidate is not None
            or ctx is None
            or digest(ctx) != digest(read_json(directory / "context.json"))
        ):
            raise ValueError("saved proposal context is stale")
        body = request(
            ctx,
            self.budget.afs_model,
            selection_policy=self.request_policy,
            service_tier=self.budget.afs_service_tier,
            api_provider=self.budget.afs_api_provider,
        )
        if proposal_request_digest(body) != proposal_request_digest(
            read_json(directory / "request.json")
        ):
            raise ValueError("saved proposal request changed")
        raw = provider.extract_proposal(response)
        try:
            candidate = selected_probe(raw, ctx, self._memory())
        except NoEligibleEndpoint as exc:
            if self.budget.reproposal_policy != "bounded-rejection-v1":
                raise
            rejection = {
                "reason": "no_eligible_endpoint",
                "endpoints": exc.rejections,
                "robot_launched": False,
                "budget_consumed": "one AFS request; no rollout intent",
            }
            atomic_json(directory / "rejection.json", rejection)
            row["artifacts"]["rejection.json"] = _hash_file(directory / "rejection.json")
            row["rejection"] = rejection
            self.state.update(selected=None, pending=None, status="READY", reason=None)
            self._save("proposal_rejected", {"id": row["id"], **rejection})
            return
        candidate["proposal_id"] = row["id"]
        row["candidate"] = candidate
        self.state.update(selected=candidate, pending=None, status="READY", reason=None)
        self._save(
            "proposal_validated",
            {
                "id": row["id"],
                "axis": candidate["axis"],
                **(
                    {"changed_axes": candidate["changed_axes"]}
                    if "changed_axes" in candidate
                    else {}
                ),
            },
        )

    def _observe(self, attempt):
        directory = self.root / "attempts" / attempt["id"]
        ensure_not_running(directory)
        receipt = (
            read_json(directory / "receipt.json")
            if (directory / "receipt.json").is_file()
            else None
        )
        record = read_goal_run(
            RunInput(path=str(directory / "rollout"), stage=attempt["candidate"]["stage"])
        )
        if receipt is None and record.status not in {"VALID", "INCONCLUSIVE"}:
            raise RuntimeError("ambiguous rollout intent; inspect evidence, never resend")
        error = "external_interrupt" if receipt and receipt.get("interrupted") else None
        if receipt and receipt.get("returncode") != 0:
            error = "runner_nonzero_exit"
        if record.status == "VALID" and not error:
            p = read_json(directory / "rollout/protocol.json")
            params, geometry, _ = _scene_parameters(directory / "rollout", p)
            expected = self.cfg.scene(attempt["candidate"]["parameters"]).model_dump()
            if (
                record.condition_id != self.plan["condition_id"]
                or params != expected
                or geometry != self.plan["geometry_id"]
                or record.policy_origin != self.plan["execution_origin"]
            ):
                error = "robot_condition_or_scene_drift"
            elif any(record.evidence_id == r.evidence_id for r in self._records()):
                error = "duplicate_evidence_not_new_execution"
        attempt["raw_episode"] = record.model_dump()
        if error:
            record = EpisodeRecord.model_validate(
                {
                    **record.model_dump(),
                    "status": "INCONCLUSIVE",
                    "task_outcome": "INCONCLUSIVE",
                    "exclusion_reason": error,
                    "attribution": None,
                }
            )
        if record.status == "VALID":
            record = classify_for_search(
                record, self.cfg.scene_schema, self.budget.taxonomy_profile
            )
        attempt.update(episode=record.model_dump(), receipt=receipt)
        self.state.update(
            pending=None,
            status="READY" if record.status == "VALID" else "NEEDS_ATTENTION",
            reason=None if record.status == "VALID" else "excluded_rollout",
        )
        self._save(
            "observed",
            {"id": attempt["id"], "status": record.status, "outcome": record.task_outcome},
        )

    def run(
        self,
        *,
        live=False,
        max_new_attempts=None,
        continue_after_exclusion=False,
        max_new_afs_requests=None,
    ):
        if not live:
            raise ValueError("explicit --live required for API and robot execution")
        if self.plan["execution_origin"] not in {"openai_api", "openrouter_api"} and isinstance(
            self.runner, LocalGoalRunner
        ):
            raise ValueError("synthetic history cannot launch the live robot runner")
        if self.plan["execution_origin"] == "openai_api" and not os.getenv("OPENAI_API_KEY"):
            raise ValueError("OPENAI_API_KEY is required in this process")
        if self.plan["execution_origin"] == "openrouter_api" and not os.getenv(
            "OPENROUTER_API_KEY"
        ):
            raise ValueError("OPENROUTER_API_KEY is required in this process")
        if max_new_attempts is not None and (
            type(max_new_attempts) is not int or max_new_attempts < 0
        ):
            raise ValueError("max_new_attempts must be nonnegative")
        if max_new_afs_requests is not None and (
            type(max_new_afs_requests) is not int or max_new_afs_requests < 1
        ):
            raise ValueError("max_new_afs_requests must be positive")
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            try:
                return self._run(max_new_attempts, continue_after_exclusion, max_new_afs_requests)
            except BaseException as exc:
                error = {
                    "type": type(exc).__name__,
                    "message": clean(str(exc)),
                    "exception_chain": exception_detail(exc),
                    "utc": stamp(),
                }
                atomic_json(self.root / "errors" / f"{error['utc']}.json", error)
                self.state.update(
                    status="NEEDS_ATTENTION",
                    reason="operator_interrupted"
                    if isinstance(exc, KeyboardInterrupt)
                    else "execution_or_validation_error",
                )
                self._save("attention_required", error)
                raise

    def _run(self, max_new_attempts, continue_after_exclusion, max_new_afs_requests=None):
        initial_requests = len(self.state["proposals"])
        self._fresh()
        pending = self.state["pending"]
        if pending:
            if pending["kind"] == "proposal":
                self._finish_proposal(self.state["proposals"][pending["index"]])
            else:
                self._observe(self.state["attempts"][pending["index"]])
        if self.state["status"] == "NEEDS_ATTENTION":
            interrupted = self.state["reason"] == "operator_interrupted"
            if not interrupted and (
                self.state["reason"] != "excluded_rollout" or not continue_after_exclusion
            ):
                return self.summary()
            self.state.update(status="READY", reason=None)
            self._save(
                "resume_after_interruption" if interrupted else "operator_continues_after_exclusion"
            )
        launched = 0
        while len(self.state["attempts"]) < self.budget.max_attempts:
            valid = sum(
                a.get("episode", {}).get("status") == "VALID" for a in self.state["attempts"]
            )
            if (
                self.budget.valid_rollout_target is not None
                and valid >= self.budget.valid_rollout_target
            ):
                self.state.update(status="COMPLETE", reason="valid_rollout_target_complete")
                self._save("complete")
                return self.summary()
            if max_new_attempts is not None and launched >= max_new_attempts:
                break
            self._fresh()
            if self.state["selected"] is None:
                candidate, ctx = self._selection()
                if candidate is None:
                    if ctx is None or len(self.state["proposals"]) >= self.budget.max_afs_requests:
                        self.state.update(
                            status="BUDGET_EXHAUSTED",
                            reason=self._selection_stop_reason(ctx),
                        )
                        self._save("selection_budget_stop")
                        return self.summary()
                    if max_new_afs_requests is not None and (
                        len(self.state["proposals"]) - initial_requests >= max_new_afs_requests
                    ):
                        self.state.update(status="READY", reason="invocation_afs_limit")
                        self._save("invocation_afs_limit")
                        return self.summary()
                    self._proposal(ctx)
                    if self.state["selected"] is None:
                        continue  # A completed rejected proposal consumed an AFS slot.
                else:
                    self.state["selected"] = candidate
                    self._save("local_candidate_selected", {"axis": candidate["axis"]})
            candidate = self.state["selected"]
            # Validate saved selection again after interruption and before spending.
            scheduled, ctx = self._selection()
            if "proposal_id" in candidate:
                row = next(
                    p for p in self.state["proposals"] if p["id"] == candidate["proposal_id"]
                )
                if candidate != row["candidate"] or ctx is None:
                    raise ValueError("saved hypothesis no longer eligible")
                raw = self._proposal_raw(row)
                expected = {**selected_probe(raw, ctx, self._memory()), "proposal_id": row["id"]}
                if expected != candidate:
                    raise ValueError("saved candidate selection mismatch")
            elif scheduled != candidate:
                raise ValueError("saved local candidate no longer eligible")
            if self.plan.get("scene_domain") is not None:
                from clear_path.search_domain import check_parameters

                check_parameters(candidate["parameters"], self.plan["scene_domain"])
            self.cfg.scene(candidate["parameters"])  # strict scene compilation before intent
            attempt = {"id": f"attempt_{len(self.state['attempts']):05d}", "candidate": candidate}
            self.state["attempts"].append(attempt)
            self.state.update(
                selected=None, pending={"kind": "rollout", "index": len(self.state["attempts"]) - 1}
            )
            self._save(
                "rollout_intent",
                {
                    "id": attempt["id"],
                    "axis": candidate["axis"],
                    **(
                        {"changed_axes": candidate["changed_axes"]}
                        if "changed_axes" in candidate
                        else {}
                    ),
                },
            )
            directory = self.root / "attempts" / attempt["id"]
            self.runner(self.cfg, directory, candidate["parameters"])
            launched += 1
            self._fresh()
            self._observe(attempt)
            if self.state["status"] == "NEEDS_ATTENTION":
                return self.summary()
        if len(self.state["attempts"]) == self.budget.max_attempts:
            excluded = any(a["episode"]["status"] != "VALID" for a in self.state["attempts"])
            valid = sum(a["episode"]["status"] == "VALID" for a in self.state["attempts"])
            target = self.budget.valid_rollout_target
            self.state.update(
                status=(
                    "TARGET_NOT_REACHED"
                    if target is not None and valid < target
                    else "COMPLETE_WITH_EXCLUSIONS"
                    if excluded
                    else "COMPLETE"
                ),
                reason="attempt_cap_before_valid_target"
                if target is not None and valid < target
                else "fixed_attempt_budget_complete",
            )
            self._save("complete")
        return self.summary()

    def summary(self):
        attempts, proposals = self.state["attempts"], self.state["proposals"]
        rows = [a["episode"] for a in attempts if "episode" in a]
        selection_costs = {}
        for field in ("input_tokens", "output_tokens"):
            values = [(p.get("usage") or {}).get(field) for p in proposals]
            valid = [v for v in values if type(v) is int and v >= 0]
            selection_costs[field] = {
                "observed": sum(valid) if valid else None,
                "missing_requests": len(proposals) - len(valid),
            }
        if self.plan.get("scene_domain") is not None:
            from clear_path.search_domain import checked_domain

            axes = checked_domain(self.plan["scene_domain"], self.cfg.scene_schema)
        else:
            axes = self.cfg.design()["axes"]
        return {
            "session": str(self.root),
            "mode": self.mode,
            "status": self.state["status"],
            "reason": self.state["reason"],
            "pending": self.state["pending"],
            "recovery": read_json(self.root / "recovery.json")
            if self.state["lock"].get("recovery_sha256")
            else None,
            "budget": self.plan["budget"],
            "attempted": len(attempts),
            "valid": sum(r["status"] == "VALID" for r in rows),
            "valid_rollout_target": self.budget.valid_rollout_target,
            "robot_api_call_upper_bound": self.plan["robot_api_call_upper_bound"],
            "afs_requests_attempted": len(proposals),
            "afs_proposals_rejected": sum("rejection" in p for p in proposals),
            "afs_requests_remaining": max(0, self.budget.max_afs_requests - len(proposals)),
            "pass": sum(r["status"] == "VALID" and r["task_outcome"] == "PASS" for r in rows),
            "fail": sum(r["status"] == "VALID" and r["task_outcome"] == "FAIL" for r in rows),
            "excluded": sum(r["status"] != "VALID" for r in rows),
            "new_only_discovery_metrics": calculate_discovery_metrics(
                [EpisodeRecord.model_validate(r) for r in rows],
                **metric_options(self.cfg.scene_schema, self.budget.taxonomy_profile),
            ),
            "scheduler": accounting(attempts, axes, self.budget),
            **self._breadth_summary(attempts, axes),
            "new_execution_costs": costs(rows, len(attempts)),
            "inherited_history_costs": costs(self.plan["history"], len(self.plan["history"])),
            "inherited_afs_selection_costs": {
                "status": "not_supplied_by_robot_archives",
                "observed": None,
            },
            "selection_costs": selection_costs,
            "selection_wall_s_observed": sum(p.get("wall_s", 0) for p in proposals),
            "selection_wall_missing_requests": sum("wall_s" not in p for p in proposals),
            "rollout_wall_s_observed": sum(
                (a.get("receipt") or {}).get("wall_s", 0) for a in attempts
            ),
            "rollout_wall_missing_attempts": sum(
                (a.get("receipt") or {}).get("wall_s") is None for a in attempts
            ),
            "limits": LIMITS,
        }

    def _breadth_summary(self, attempts, axes):
        if self.budget.exploration_policy != "breadth-v1":
            return {}
        from collections import Counter

        from failure_client.methods.breadth_policy import allocation, behavior_relevance

        selectable = accounting(attempts, axes, self.budget)["selectable_axes"]
        forms = Counter(a["candidate"]["exploration"]["form"] for a in attempts)
        return {
            "exploration_allocation": {
                **allocation(
                    attempts,
                    selectable,
                    relevance=behavior_relevance(self._memory())
                    if self.budget.factor_allocation == "behavior-relevance-v1"
                    else None,
                ),
                "form_attempts": dict(forms),
                "next_slot_is_executable": self.state["status"] == "READY",
            }
        }

    def report(self):
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._verify_lock()
            self._verify_evidence()
            output = self.root / "reports" / stamp()
            output.mkdir(parents=True, exist_ok=False)
            summary = self.summary()
            atomic_json(output / "summary.json", summary)
            atomic_json(output / "attempts.json", self.state["attempts"])
            atomic_json(output / "proposals.json", self.state["proposals"])
            atomic_json(output / "ledger.json", self.store.ledger())
            memory = self._memory()
            export_failure_memory(output / "behavior", memory)
            records = self._records()
            diagnostics = {
                "new_execution_only": search_diagnostics(
                    memory, records[len(self.plan["history"]) :]
                ),
                "reviewed_plus_new": search_diagnostics(memory, records),
                "claim": "Descriptive development observations; not benchmark milestones or Gain",
            }
            reviews = experiment_reviews(
                [{"method": "unassigned", "seed": 0, **a} for a in self.state["attempts"]], memory
            )
            atomic_json(output / "search_diagnostics.json", diagnostics)
            atomic_json(output / "hypothesis_reviews.json", reviews)
            sections = []
            for p in self.state["proposals"]:
                if "rejection" in p:
                    sections.append(
                        f"<h2>{escape(p['id'])} · 후보 거절 · 로봇 미실행</h2><pre>"
                        + escape(json.dumps(p["rejection"], indent=2, ensure_ascii=False))
                        + "</pre>"
                    )
            for a in self.state["attempts"]:
                c, r = a["candidate"], a.get("episode", {})
                label = (
                    f"{a['id']} · {c['strategy']} · {c['axis']} · "
                    f"{r.get('task_outcome', 'PENDING')}"
                )
                detail = {
                    "parameters": c["parameters"],
                    "hypothesis_or_evidence": c["evidence"],
                    "scheduler": c["scheduler"],
                    "termination_reason": r.get("termination_reason"),
                    "exclusion_reason": r.get("exclusion_reason"),
                    "measures": r.get("measures"),
                }
                if "branch_audit" in c:
                    detail["branch_audit"] = c["branch_audit"]
                if "exploration" in c:
                    detail["exploration"] = c["exploration"]
                    detail["changed_axes"] = c["changed_axes"]
                if self.budget.reproposal_policy == "bounded-rejection-v1":
                    detail["endpoint_selection_audit"] = c.get("selection_audit")
                links = []
                for name, title in (("report.html", "로봇 행동 보고서"), ("rollout.mp4", "MP4")):
                    if (self.root / "attempts" / a["id"] / "rollout" / name).is_file():
                        links.append(
                            f'<a href="../../attempts/{a["id"]}/rollout/{name}">{title}</a>'
                        )
                sections.append(
                    f"<h2>{escape(label)}</h2>"
                    + " · ".join(links)
                    + "<pre>"
                    + escape(json.dumps(detail, indent=2, ensure_ascii=False))
                    + "</pre>"
                )
            (output / "report.html").write_text(
                '<!doctype html><meta charset="utf-8"><title>Autonomous development AFS</title>'
                "<h1>행동 근거 기반 자동 개발 탐색</h1>"
                "<p>외부 이력을 사용합니다. AFS/Random 비교가 아닙니다. "
                "가설·관측 경계는 원인 또는 실패 유형 검증이 아닙니다.</p>"
                '<a href="behavior/index.html">행동 근거·반복·관측 경계·회귀 자산</a>'
                '<p><a href="search_diagnostics.json">행동 패턴 반복·관측 경계 추이</a> · '
                '<a href="hypothesis_reviews.json">가설과 실제 결과 연결</a></p>'
                "<pre>"
                + escape(json.dumps(summary, indent=2, ensure_ascii=False))
                + "</pre>"
                + "".join(sections),
                encoding="utf-8",
            )
            atomic_json(
                output / "manifest.json",
                {
                    "artifacts": [
                        {"path": str(p.relative_to(output)), "sha256": _hash_file(p)}
                        for p in sorted(output.rglob("*"))
                        if p.is_file()
                    ]
                },
            )
            return output / "report.html"
