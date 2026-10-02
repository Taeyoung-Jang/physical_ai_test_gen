"""Bounded, resumable local AFS/Random pilot. Every side effect has a persisted intent.

Uncertain calls are never automatically resent. Actual robot outcomes still come only
from the unmodified goal evaluator and P0 archive verifier.
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from clear_path.fixture import identity
from failure_client.archive.regression_cases import _scene_parameters, build_failure_memory
from failure_client.evaluation.goal_run_reader import _hash_file, read_goal_run, read_json
from failure_client.evaluation.research_records import ComparisonDesign, EpisodeRecord, RunInput
from failure_client.methods.base import CandidateObservation
from failure_client.methods.behavior_feedback import (
    BehaviorMethodState,
    boundary_candidate,
    choose_probe,
    feedback_context,
    proposal_request,
    repeat_candidate,
    seeded,
    uniform_scene,
)
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.reporting.discovery_report import write_discovery_report
from failure_client.storage.research_store import ResearchStore
from llm_afs import provider
from llm_afs.behavior import EvidenceReferenceError, digest
from robot_vlm.debug_log import clean, exception_detail
from robot_vlm.navigation_completion import profile_from_protocol

from .local_goal_adapter import LocalGoalRunner, atomic_json
from .proposal_recovery import verify_recovery
from .research_protocol import CampaignConfig, environment_fingerprint


class NeedsAttention(RuntimeError):
    pass


class CampaignLimit(NeedsAttention):
    pass


def _arm(method, seed):
    return f"{method}:{seed}"


class ResearchCampaign:
    def __init__(self, root, *, runner=None, proposer=None, fingerprint=None, on_event=None):
        self.root = Path(root).resolve()
        if not (self.root / "campaign.sqlite3").is_file():
            raise ValueError("initialize a new campaign first")
        self.store = ResearchStore(self.root)
        self.runner = runner or LocalGoalRunner()
        self.proposer = proposer or provider.call
        self.fingerprint = fingerprint or environment_fingerprint
        self.on_event = on_event
        self.state, self.revision = self.store.load()
        self.config = CampaignConfig.model_validate(self.state["lock"]["config"])
        self._verify_lock()

    @classmethod
    def create(cls, root, config, *, fingerprint=None, execution_origin="openai_api"):
        config = CampaignConfig.model_validate(config.model_dump())
        fingerprint = fingerprint or environment_fingerprint
        environment = fingerprint(config)  # Read-only preflight before making an output.
        root = Path(root).resolve()
        root.mkdir(parents=True, exist_ok=False)
        lock = {
            "config": config.model_dump(),
            "design": config.design(),
            "environment": environment,
            "execution_origin": execution_origin,
        }
        atomic_json(root / "protocol.json", {"lock": lock, "lock_sha256": digest(lock)})
        order = []
        for seed in config.seeds:
            methods = ["afs", "random"]
            seeded(seed, "method-order-v1").shuffle(methods)
            order.extend({"method": m, "seed": seed} for m in methods)
        state = {
            "schema_version": "research-campaign-state-v1",
            "lock": lock,
            "lock_sha256": digest(lock),
            "status": "READY",
            "reason": None,
            "condition_id": None,
            "order": order,
            "turn": 0,
            "pending": None,
            "attempts": [],
            "proposals": [],
            "checkpoints": {},
        }
        ResearchStore(root).save(state, -1, "created", config.design())
        return root

    def _verify_lock(self):
        saved = read_json(self.root / "protocol.json")
        if digest(self.state["lock"]) != self.state["lock_sha256"] or saved != {
            "lock": self.state["lock"],
            "lock_sha256": self.state["lock_sha256"],
        }:
            raise ValueError("immutable campaign protocol mismatch")
        verify_recovery(self.root, self.state)

    def _save(self, event, detail=None):
        self.revision = self.store.save(self.state, self.revision, event, detail)
        if self.on_event is not None:
            self.on_event(event, detail or {})

    def _fresh(self):
        if self.fingerprint(self.config) != self.state["lock"]["environment"]:
            raise NeedsAttention(
                "code, dependency or robot resource drift; start a separate campaign"
            )

    def records(self, method=None, seed=None):
        rows = []
        for a in self.state["attempts"]:
            if (
                "episode" in a
                and (method is None or a["method"] == method)
                and (seed is None or a["seed"] == seed)
            ):
                rows.append(EpisodeRecord.model_validate(a["episode"]))
        return rows

    def _valid(self, method, seed):
        return sum(r.status == "VALID" for r in self.records(method, seed))

    def _next_arm(self):
        order = self.state["order"]
        for offset in range(len(order)):
            index = (self.state["turn"] + offset) % len(order)
            arm = order[index]
            if self._valid(**arm) < self.config.valid_budget_per_seed:
                attempts = sum(
                    a["method"] == arm["method"] and a["seed"] == arm["seed"]
                    for a in self.state["attempts"]
                )
                if attempts >= self.config.max_attempts_per_arm:
                    self.state.update(status="INCOMPLETE", reason="attempt_cap")
                    self._save("attempt_cap", arm)
                    return None
                self.state["turn"] = index + 1
                return arm
        self.state.update(status="COMPLETE", reason=None)
        self._save("budget_complete")
        return None

    def _memory(self, seed):
        rows = self.records("afs", seed)
        # Re-import and compare full records: source changes must not influence later selection.
        for row in rows:
            if row.status == "VALID" and read_goal_run(row.source) != row:
                raise NeedsAttention("completed evidence changed; cannot continue search")
        if self.config.taxonomy_profile != "none":
            from failure_client.evaluation.failure_taxonomy import classify_record

            rows = [classify_record(row) for row in rows]
        return build_failure_memory(rows)

    def _candidate(self, arm):
        method, seed = arm["method"], arm["seed"]
        valid = self._valid(method, seed)
        attempts = sum(a["method"] == method and a["seed"] == seed for a in self.state["attempts"])
        if valid < self.config.cold_start:
            return {
                "parameters": uniform_scene(
                    seed, "paired-cold", valid, schema=self.config.scene_schema
                ),
                "strategy": "paired_uniform_cold_start",
                "stage": "cold_start",
            }
        if method == "random":
            return {
                "parameters": uniform_scene(
                    seed, "random", attempts, schema=self.config.scene_schema
                ),
                "strategy": "full_domain_uniform",
                "stage": "discovery",
            }
        memory = self._memory(seed)
        slot = valid - self.config.cold_start
        strategy = self.config.strategy_cycle[slot % len(self.config.strategy_cycle)]
        if strategy == "exploration":
            return {
                "parameters": uniform_scene(
                    seed, "afs-exploration", attempts, schema=self.config.scene_schema
                ),
                "strategy": "independent_exploration",
                "stage": "discovery",
            }
        if strategy == "repeat":
            # Alternate success/failure controls when both exist; mixed cases remain eligible.
            desired = (
                "success_control"
                if slot // len(self.config.strategy_cycle) % 2
                else "observed_failure"
            )
            return repeat_candidate(memory, desired=desired)
        if strategy == "boundary":
            if self.config.selection_policy == "hypothesis-v2":
                candidate = repeat_candidate(memory, mixed_only=True)
                if candidate is not None:
                    return candidate
            candidate = boundary_candidate(memory)
            if candidate is not None:
                return candidate
        # No observed bracket: request a new hypothesis, not a fabricated boundary/fallback.
        count = sum(p["seed"] == seed for p in self.state["proposals"])
        if count >= self.config.max_proposals_per_seed:
            raise CampaignLimit("AFS request cap reached; no automatic fallback")
        ctx = feedback_context(
            memory,
            history_limit=self.config.history_limit,
            remaining=self.config.valid_budget_per_seed - valid,
            scene_schema=self.config.scene_schema,
            selection_policy=self.config.selection_policy,
        )
        body = proposal_request(ctx, self.config.afs_model)
        pid = f"proposal_{len(self.state['proposals']):05d}"
        row = {
            "id": pid,
            "seed": seed,
            "context": ctx,
            "request": body,
            "status": "PENDING",
            "requested_slot": strategy,
            "wall_s": None,
            "usage": None,
            "request_utf8_bytes": len(json.dumps(body, ensure_ascii=False).encode("utf-8")),
            "response_received": False,
        }
        self.state["proposals"].append(row)
        self.state["pending"] = {"kind": "proposal", "id": pid, "arm": arm}
        self._save("proposal_intent", {"id": pid, "context_sha256": digest(ctx)})
        directory = self.root / "proposals" / pid
        atomic_json(directory / "request.json", body)
        started = time.monotonic()
        try:
            response = self.proposer(body, timeout=self.config.afs_timeout_s)
            atomic_json(directory / "response.json", response)
            row["wall_s"] = time.monotonic() - started
            return self._finish_proposal(row)
        except Exception as exc:
            row.update(error_type=type(exc).__name__, wall_s=time.monotonic() - started)
            diagnostic = {"exception_chain": exception_detail(exc)}
            if isinstance(exc, EvidenceReferenceError):
                diagnostic["validation"] = {
                    "code": "unknown_evidence_reference",
                    "unknown": exc.unknown,
                    "allowed": exc.allowed,
                }
            atomic_json(directory / "error.json", diagnostic)
            self._save("proposal_error", {"id": pid, "error_type": type(exc).__name__})
            raise NeedsAttention(
                f"{pid}: proposal failed; inspect saved evidence, no retry"
            ) from None

    def _proposal_memory(self, row):
        # The model call or a crash may have separated selection from execution.
        # Never reuse a READY proposal without rechecking the evidence it used.
        memory = self._memory(row["seed"])
        current = feedback_context(
            memory,
            history_limit=self.config.history_limit,
            remaining=self.config.valid_budget_per_seed - self._valid("afs", row["seed"]),
            scene_schema=self.config.scene_schema,
            selection_policy=self.config.selection_policy,
        )
        if digest(current) != digest(row["context"]):
            raise NeedsAttention("saved proposal context differs from current verified evidence")
        return memory

    def _finish_proposal(self, row):
        response = read_json(self.root / "proposals" / row["id"] / "response.json")
        row.update(
            response_received=True,
            usage=response.get("usage"),
            returned_model=response.get("model"),
            response_id=response.get("id"),
        )
        self._save("proposal_response", {"id": row["id"]})
        candidate = choose_probe(
            provider.extract_proposal(response), row["context"], self._proposal_memory(row)
        )
        candidate["proposal_id"] = row["id"]
        row.update(status="READY", candidate=candidate)
        self._save("proposal_validated", {"id": row["id"]})
        return candidate

    def _prepare_attempt(self, arm, candidate):
        config = self.config.scene(candidate["parameters"])
        aid = f"attempt_{len(self.state['attempts']):05d}"
        attempt = {
            "id": aid,
            **arm,
            "candidate": candidate,
            "scene_revision": identity(config),
            "status": "PENDING",
            "receipt": None,
        }
        self.state["attempts"].append(attempt)
        self.state["pending"] = {"kind": "rollout", "id": aid}
        self._save("rollout_intent", {"id": aid, **arm, "strategy": candidate["strategy"]})
        directory = self.root / "attempts" / aid
        directory.mkdir(parents=True, exist_ok=False)
        atomic_json(directory / "candidate.json", candidate)
        return attempt, directory

    def _finish_attempt(self, a, receipt=None):
        directory = self.root / "attempts" / a["id"]
        if receipt is None and (directory / "receipt.json").exists():
            receipt = read_json(directory / "receipt.json")
        source = RunInput(
            path=str(directory / "rollout"),
            method=a["method"],
            seed=a["seed"],
            stage=a["candidate"]["stage"],
        )
        record = read_goal_run(source)
        a["raw_episode"] = record.model_dump()
        if receipt and receipt.get("interrupted"):
            record = EpisodeRecord(
                source=source,
                status="INCONCLUSIVE",
                exclusion_reason="external_watchdog_or_interrupt",
            )
        elif record.status == "VALID":
            protocol = read_json(directory / "rollout/protocol.json")
            robot = self.config.robot
            if (
                protocol["scene_revision"] != a["scene_revision"]
                or protocol["scene_config"]
                != self.config.scene(a["candidate"]["parameters"]).model_dump()
                or protocol.get("model") != robot.model
                or protocol["max_calls"] != robot.max_calls
                or protocol["max_simulation_s"] != robot.max_seconds
                or protocol.get("push_enabled") != robot.enable_push
                or profile_from_protocol(protocol) != robot.navigation_completion
                or protocol.get("http_read_timeout_s") != robot.response_timeout
                or protocol["policy_origin"] != self.state["lock"]["execution_origin"]
            ):
                self.state.update(status="INCOMPLETE", reason="campaign_contract_mismatch")
                record = EpisodeRecord(
                    source=source, status="INVALID", exclusion_reason="campaign_contract_mismatch"
                )
            elif record.evidence_id in {r.evidence_id for r in self.records() if r.evidence_id}:
                record = EpisodeRecord(
                    source=source, status="INVALID", exclusion_reason="duplicate_core_evidence"
                )
            elif (
                self.config.scene_schema in {"clear-path-corridor-v2", "clear-path-obstacles-v3"}
                and _scene_parameters(directory / "rollout", protocol)[0] is None
            ):
                self.state.update(status="INCOMPLETE", reason="scene_geometry_mismatch")
                record = EpisodeRecord(
                    source=source, status="INVALID", exclusion_reason="scene_geometry_mismatch"
                )
            elif self.state["condition_id"] is None:
                self.state["condition_id"] = record.condition_id
        a.update(status="OBSERVED", episode=record.model_dump(), receipt=receipt)
        key = _arm(a["method"], a["seed"])
        method = BehaviorMethodState(self.state["checkpoints"].get(key))
        method.observe(
            [
                CandidateObservation(
                    candidate_id=a["id"],
                    status="EVALUATED" if record.status == "VALID" else "INDETERMINATE",
                    failure=record.task_outcome == "FAIL" if record.status == "VALID" else None,
                    details={"evidence_id": record.evidence_id, "reason": record.exclusion_reason},
                )
            ]
        )
        self.state["checkpoints"][key] = method.state_dict()
        self.state["pending"] = None
        condition_changed = (
            record.status == "VALID" and record.condition_id != self.state["condition_id"]
        )
        if condition_changed:
            # Stop and observation must survive the same transaction/crash boundary.
            self.state.update(status="INCOMPLETE", reason="condition_or_returned_model_changed")
        self._save(
            "observed_and_checkpointed",
            {"id": a["id"], "status": record.status, "outcome": record.task_outcome},
        )
        if condition_changed:
            self._save("condition_mismatch", {"id": a["id"]})

    def _recover(self):
        pending = self.state["pending"]
        if pending is None:
            return None
        if pending["kind"] == "rollout":
            a = next(a for a in self.state["attempts"] if a["id"] == pending["id"])
            directory = self.root / "attempts" / a["id"]
            if not (directory / "receipt.json").exists() and (directory / "process.json").exists():
                try:
                    os.kill(read_json(directory / "process.json")["pid"], 0)
                except ProcessLookupError:
                    pass
                else:
                    raise NeedsAttention(f"{a['id']}: child process may still be active")
            if not (
                (directory / "receipt.json").is_file()
                or (directory / "rollout/manifest.json").is_file()
            ):
                raise NeedsAttention(
                    f"{a['id']}: execution ambiguous; verify process before resolving"
                )
            self._finish_attempt(a)
            return None
        p = next(p for p in self.state["proposals"] if p["id"] == pending["id"])
        if p["status"] == "READY":
            self._proposal_memory(p)
            return pending["arm"], p["candidate"]
        if not (self.root / "proposals" / p["id"] / "response.json").exists():
            raise NeedsAttention(f"{p['id']}: API completion unknown; will not resend")
        return pending["arm"], self._finish_proposal(p)

    def run(self, *, max_new_attempts=None):
        if max_new_attempts is not None and max_new_attempts < 0:
            raise ValueError("max_new_attempts must be nonnegative")
        launched = 0
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._verify_lock()
            if self.state["status"] in {"COMPLETE", "INCOMPLETE"}:
                return self.summary()
            try:
                self._fresh()
                recovered = self._recover()
                if self.state["status"] == "INCOMPLETE":
                    return self.summary()
                self.state.update(status="RUNNING", reason=None)
                self._save("resume")
                while max_new_attempts is None or launched < max_new_attempts:
                    self._fresh()
                    if recovered:
                        arm, candidate = recovered
                        recovered = None
                    else:
                        arm = self._next_arm()
                        if arm is None:
                            break
                        candidate = self._candidate(arm)
                    # Selection may include a long external inference wait. Recheck
                    # frozen code/resources before launching, not only afterwards.
                    self._fresh()
                    a, directory = self._prepare_attempt(arm, candidate)
                    launched += 1
                    receipt = self.runner(self.config, directory, candidate["parameters"])
                    atomic_json(directory / "receipt.json", receipt)
                    self._fresh()
                    self._finish_attempt(a, receipt)
                    if self.state["status"] == "INCOMPLETE":
                        break
                    if receipt.get("interrupted"):
                        self.state.update(status="READY", reason="external_interruption")
                        self._save("invocation_interrupted", {"id": a["id"]})
                        break
                else:
                    self.state.update(status="READY", reason="invocation_limit")
                    if all(
                        self._valid(**arm) == self.config.valid_budget_per_seed
                        for arm in self.state["order"]
                    ):
                        self.state.update(status="COMPLETE", reason=None)
                    self._save("invocation_finished")
            except Exception as exc:
                if self.state["status"] != "INCOMPLETE":
                    self.state.update(
                        status="INCOMPLETE"
                        if isinstance(exc, CampaignLimit)
                        else "NEEDS_ATTENTION",
                        reason=type(exc).__name__,
                    )
                atomic_json(
                    self.root / "last_error.json", {"exception_chain": exception_detail(exc)}
                )
                self._save("attention_required", {"error_type": type(exc).__name__})
                raise
        return self.summary()

    def abandon_pending(self, identifier, note):
        """Explicit acknowledgement after the operator verifies no process/request is active."""
        if not note.strip():
            raise ValueError("an operator resolution note is required")
        note = clean(note)
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._verify_lock()
            pending = self.state["pending"]
            if pending is None or pending["id"] != identifier:
                raise ValueError("not the pending operation")
            if pending["kind"] == "rollout":
                directory = self.root / "attempts" / identifier
                if (directory / "rollout/manifest.json").exists():
                    raise ValueError("completed evidence exists; resume to ingest it")
                if (directory / "process.json").exists():
                    pid = read_json(directory / "process.json")["pid"]
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        pass
                    else:
                        raise ValueError("process may still be active; resolve it externally first")
                a = next(a for a in self.state["attempts"] if a["id"] == identifier)
                # Explicitly unresolved execution stays excluded; no reconstructed outcome.
                a["resolution_note"] = note
                self._finish_attempt(a, {"interrupted": "operator_abandoned", "wall_s": None})
            else:
                p = next(p for p in self.state["proposals"] if p["id"] == identifier)
                if p["status"] == "READY":
                    raise ValueError("validated proposal exists; resume it")
                response_path = self.root / "proposals" / identifier / "response.json"
                if response_path.exists():
                    memory = self._proposal_memory(p)
                    try:
                        response = read_json(response_path)
                        choose_probe(provider.extract_proposal(response), p["context"], memory)
                    except (ValueError, KeyError, TypeError, AttributeError):
                        # A malformed/refused/non-actionable response can be explicitly
                        # abandoned, but a usable saved response must first be resumed.
                        pass
                    else:
                        raise ValueError("usable saved proposal exists; resume to validate it")
                p.update(status="ABANDONED", resolution_note=note)
                self.state["pending"] = None
            self.state.update(status="READY", reason="explicit_resolution")
            self._save("operator_resolution", {"id": identifier, "note": note})

    def summary(self):
        rows = self.records()
        raw = [a.get("raw_episode", {}) for a in self.state["attempts"]]
        robot_calls = [r["robot_api_calls"] for r in raw if r.get("robot_api_calls") is not None]
        usage = [p.get("usage") or {} for p in self.state["proposals"]]
        tokens = {}
        for key in ("input_tokens", "output_tokens"):
            values = [u[key] for u in usage if type(u.get(key)) is int and u[key] >= 0]
            tokens[key + "_observed"] = sum(values) if values else None
            tokens[key + "_missing_requests"] = len(usage) - len(values)
        robot_tokens = {}
        for key in ("observed_input_tokens", "observed_output_tokens"):
            values = [r[key] for r in raw if r.get(key) is not None]
            robot_tokens[key] = sum(values) if values else None
            robot_tokens[key + "_missing_attempts"] = len(raw) - len(values)
        return {
            "campaign": str(self.root),
            "status": self.state["status"],
            "reason": self.state["reason"],
            "pending": self.state["pending"],
            "recovery": (
                {
                    "claim": "operator_assisted_continuation_not_prospective_comparison",
                    "audit_sha256": self.state["lock"]["recovery_sha256"],
                    "audit_path": str(self.root / "recovery.json"),
                    "inherited_costs_included": True,
                }
                if self.state["lock"].get("recovery_sha256")
                else None
            ),
            "arms": [
                {
                    **arm,
                    "valid": self._valid(**arm),
                    "budget": self.config.valid_budget_per_seed,
                    "attempts": sum(
                        a["method"] == arm["method"] and a["seed"] == arm["seed"]
                        for a in self.state["attempts"]
                    ),
                }
                for arm in self.state["order"]
            ],
            "excluded": sum(r.status != "VALID" for r in rows),
            "afs_requests_attempted": len(self.state["proposals"]),
            "afs_tokens": tokens,
            "robot_tokens": robot_tokens,
            "robot_usage_audit": {
                "calls_with_usage": sum(r.get("calls_with_token_usage", 0) for r in raw),
                "calls_missing_usage_observed": sum(
                    r["usage_audit"]["calls_missing_usage"] for r in raw if r.get("usage_audit")
                )
                if any(r.get("usage_audit") for r in raw)
                else None,
                "attempts_without_usage_audit": sum(not r.get("usage_audit") for r in raw),
                "attempts_partial": sum(
                    r.get("usage_audit", {}).get("status") == "PARTIAL" for r in raw
                ),
            },
            "afs_request_utf8_bytes": [
                p.get("request_utf8_bytes") for p in self.state["proposals"]
            ],
            "robot_api_calls_observed": sum(robot_calls) if robot_calls else None,
            "robot_api_calls_missing_attempts": len(raw) - len(robot_calls),
            "afs_requests_without_usage": sum(
                p.get("usage") is None for p in self.state["proposals"]
            ),
            "afs_requests_without_wall_measure": sum(
                p["wall_s"] is None for p in self.state["proposals"]
            ),
            "afs_usage_observed": [
                p["usage"] for p in self.state["proposals"] if p.get("usage") is not None
            ],
            "afs_wall_s_observed": sum(
                p["wall_s"] for p in self.state["proposals"] if p["wall_s"] is not None
            ),
            "rollout_wall_s_observed": sum(
                (a.get("receipt") or {}).get("wall_s") or 0 for a in self.state["attempts"]
            ),
            "rollouts_without_wall_measure": sum(
                (a.get("receipt") or {}).get("wall_s") is None for a in self.state["attempts"]
            ),
            "limits": [
                "Unknown costs are not zero; usage is observed, not a billing total",
                "Optional operational family associations are not established causes; "
                "no superiority claim from synthetic tests",
            ],
        }

    def report(self, *, with_memory=False):
        with self.store.exclusive():
            self.state, self.revision = self.store.load()
            self._verify_lock()
            records = self.records()
            for a in self.state["attempts"]:
                if a.get("episode", {}).get("status") == "VALID":
                    r = EpisodeRecord.model_validate(a["episode"])
                    if read_goal_run(r.source) != r:
                        raise NeedsAttention("archived evidence changed; reporting refused")
            design = ComparisonDesign(
                domain_id=self.config.design()["domain_id"],
                sampling_distribution=self.config.design()["sampling_distribution"],
                condition_id=self.state["condition_id"] or "no_observed_condition",
                valid_budget_per_seed=self.config.valid_budget_per_seed,
                seeds=self.config.seeds,
            )
            rules = None
            if self.config.taxonomy_profile != "none":
                from failure_client.evaluation.failure_taxonomy import RULES, classify_record

                records = [classify_record(r) for r in records]
                rules = RULES
            metrics = calculate_discovery_metrics(records, design, family_rules=rules)
            metrics["campaign_execution"] = self.summary()
            memory = build_failure_memory(records) if with_memory else None
            if memory is not None:
                from failure_client.reporting.search_diagnostics import (
                    experiment_reviews,
                    search_diagnostics,
                )

                metrics["search_diagnostics"] = search_diagnostics(memory, records)
                metrics["search_diagnostics"]["experiment_reviews"] = experiment_reviews(
                    self.state["attempts"], memory
                )
            if self.state["status"] != "COMPLETE":
                metrics["comparison"] = {
                    **metrics["comparison"],
                    "status": "not_comparable",
                    "relative_gain": None,
                    "gain_target_observed": None,
                    "campaign_incomplete": True,
                }
            if self.state["lock"].get("recovery_sha256"):
                metrics["comparison"] = {
                    **metrics["comparison"],
                    "status": "not_comparable",
                    "relative_gain": None,
                    "gain_target_observed": None,
                    "per_seed": [],
                    "issues": [
                        *metrics["comparison"].get("issues", []),
                        "operator_assisted_recovery",
                    ],
                }
                metrics["limitations"].append(
                    "Operator-assisted recovery: descriptive outcomes only, "
                    "not a prospective gain claim"
                )
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
            output = self.root / "reports" / stamp
            report = write_discovery_report(
                output,
                self.root.name,
                records,
                metrics,
                memory=memory,
            )
            atomic_json(output / "campaign_ledger.json", self.store.ledger())
            atomic_json(output / "campaign_protocol.json", read_json(self.root / "protocol.json"))
            extras = ["campaign_ledger.json", "campaign_protocol.json"]
            if self.state["lock"].get("recovery_sha256"):
                atomic_json(output / "recovery.json", read_json(self.root / "recovery.json"))
                extras.append("recovery.json")
            manifest = read_json(output / "manifest.json")
            manifest["artifacts"].extend(
                {"path": name, "sha256": _hash_file(output / name)} for name in extras
            )
            atomic_json(output / "manifest.json", manifest)
            atomic_json(self.root / "latest_report.json", {"report": str(report)})
            return report
