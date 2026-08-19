"""End-to-end, crash-resumable Client experiment orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from pydantic import Field

from failure_client.api import SimulationGateway
from failure_client.archive import FailureArchive
from failure_client.candidates import CandidateValidator, InterventionBuilder
from failure_client.contracts import (
    CapabilitySnapshot,
    ContractModel,
    ExecutionSpec,
    RecordingSpec,
    ResearchContext,
    RolloutRequest,
    canonical_sha256,
)
from failure_client.evaluation import (
    EvaluationOutcome,
    FailureDefinition,
    FailureEvaluator,
)
from failure_client.methods import (
    CandidateObservation,
    FailureDiscoveryMethod,
    MethodContext,
    MethodRegistry,
    derive_repeat_seed,
)
from failure_client.registry import (
    RegistrySynchronizer,
    check_method_compatibility,
)
from failure_client.reporting import FailureCaseExporter, FailureExportResult
from failure_client.storage import (
    CandidateRecord,
    CandidateState,
    ClientRepository,
    ExperimentState,
    RolloutAttemptRecord,
    RolloutAttemptState,
    StoreConflictError,
)
from failure_client.world_model import WorldModelProjector

from .lock import ProtocolLock, build_protocol_lock, write_protocol_lock
from .protocol import ExperimentProtocol
from .rollout_coordinator import RolloutCoordinator


class ExperimentRunSummary(ContractModel):
    experiment_id: str
    state: ExperimentState
    candidate_count: int = Field(ge=0)
    observed_candidate_count: int = Field(ge=0)
    rollout_count: int = Field(ge=0)
    evaluation_count: int = Field(ge=0)
    confirmed_failure_count: int = Field(ge=0)


class ProtocolCompatibilityError(ValueError):
    pass


class ExperimentOrchestrator:
    def __init__(
        self,
        repository: ClientRepository,
        gateway: SimulationGateway,
        *,
        workspace_dir: Path,
        repository_dir: Path | None = None,
        dependency_lock_path: Path | None = None,
        method_registry: MethodRegistry | None = None,
        poll_interval_s: float = 1.0,
        max_poll_cycles: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        self.workspace_dir = workspace_dir
        self.repository_dir = repository_dir
        self.dependency_lock_path = dependency_lock_path
        self.method_registry = method_registry or MethodRegistry.with_builtins(
            load_external=True
        )
        self.poll_interval_s = poll_interval_s
        self.max_poll_cycles = max_poll_cycles
        self._sleep = sleep
        self.synchronizer = RegistrySynchronizer(repository, gateway)
        self.coordinator = RolloutCoordinator(repository, gateway, sleep=sleep)
        self.builder = InterventionBuilder()
        self.validator = CandidateValidator()
        self.evaluator = FailureEvaluator()
        self.archive = FailureArchive(repository)
        self.exporter = FailureCaseExporter(repository)

    def validate_protocol(self, protocol: ExperimentProtocol) -> dict[str, object]:
        sync = self.synchronizer.sync()
        capabilities = self.repository.get_latest_capabilities()
        self._validate_resources(protocol, capabilities)
        method, _ = self._initialize_method(protocol, capabilities)
        definition = _failure_definition(protocol)
        return {
            "status": "compatible",
            "experiment_id": protocol.experiment.experiment_id,
            "registry_revision": sync.registry_revision,
            "capability_sha256": canonical_sha256(capabilities),
            "method": f"{method.plugin_id}@{method.plugin_version}",
            "failure_definition_sha256": canonical_sha256(definition),
            "maximum_parallel_jobs": _maximum_parallel(protocol, capabilities),
        }

    def run(
        self,
        protocol: ExperimentProtocol,
        *,
        resume: bool = False,
    ) -> ExperimentRunSummary:
        experiment_id = protocol.experiment.experiment_id
        capabilities, _ = self._open_experiment(protocol, resume=resume)
        method, method_instance_id = self._initialize_method(protocol, capabilities)
        definition = _failure_definition(protocol)
        maximum_parallel = _maximum_parallel(protocol, capabilities)

        self.repository.set_experiment_state(experiment_id, ExperimentState.RUNNING_SEARCH)
        try:
            self._resume_pending(
                protocol,
                definition,
                method,
                method_instance_id,
                maximum_parallel,
            )
            while len(self.repository.list_candidates(experiment_id)) < (
                protocol.execution.candidate_budget
            ):
                if method.should_stop().should_stop:
                    break
                remaining = protocol.execution.candidate_budget - len(
                    self.repository.list_candidates(experiment_id)
                )
                proposals = method.propose(min(remaining, maximum_parallel))
                if not proposals:
                    break
                built_candidates = []
                for proposal in proposals:
                    built = self.builder.build(proposal)
                    validation = self.validator.validate(built, capabilities)
                    built_candidates.append((built, validation))
                # Candidate rows and the proposal/RNG cursor share one crash boundary.
                records = self.repository.save_candidate_batch_with_checkpoint(
                    experiment_id=experiment_id,
                    method_instance_id=method_instance_id,
                    candidates=built_candidates,
                    method_state=method.state_dict(),
                )
                self._process_candidates(
                    protocol,
                    definition,
                    method,
                    method_instance_id,
                    records,
                    maximum_parallel,
                )
            self.repository.set_experiment_state(experiment_id, ExperimentState.COMPLETED)
            self.export_experiment(experiment_id)
        except Exception:
            self.repository.set_experiment_state(experiment_id, ExperimentState.PAUSED)
            raise
        return self.summary(experiment_id, definition)

    def export_experiment(self, experiment_id: str) -> FailureExportResult:
        experiment = self.repository.get_experiment(experiment_id)
        protocol = ExperimentProtocol.model_validate(experiment["protocol"])
        definition = _failure_definition(protocol)
        return self.exporter.export(
            experiment_id=experiment_id,
            definition_sha256=canonical_sha256(definition),
            output_dir=(
                self.workspace_dir / "experiments" / experiment_id / "exports"
            ),
        )

    def summary(
        self,
        experiment_id: str,
        definition: FailureDefinition | None = None,
    ) -> ExperimentRunSummary:
        experiment = self.repository.get_experiment(experiment_id)
        candidates = self.repository.list_candidates(experiment_id)
        evaluations = self.repository.list_evaluations(experiment_id=experiment_id)
        definition_sha = canonical_sha256(definition) if definition is not None else None
        confirmed = 0
        for candidate in candidates:
            if definition_sha is None:
                continue
            try:
                case = self.repository.get_failure_case(
                    experiment_id,
                    candidate.candidate_id,
                    definition_sha,
                )
            except KeyError:
                continue
            confirmed += case.confirmed_failure
        rollout_count = sum(
            len(self.repository.list_rollout_attempts(experiment_id, item.candidate_id))
            for item in candidates
        )
        return ExperimentRunSummary(
            experiment_id=experiment_id,
            state=experiment["state"],
            candidate_count=len(candidates),
            observed_candidate_count=sum(
                item.state == CandidateState.OBSERVED for item in candidates
            ),
            rollout_count=rollout_count,
            evaluation_count=len(evaluations),
            confirmed_failure_count=confirmed,
        )

    def _open_experiment(
        self,
        protocol: ExperimentProtocol,
        *,
        resume: bool,
    ) -> tuple[CapabilitySnapshot, ProtocolLock]:
        experiment_id = protocol.experiment.experiment_id
        try:
            existing = self.repository.get_experiment(experiment_id)
        except KeyError:
            existing = None
        if existing is not None:
            if not resume:
                raise StoreConflictError(
                    f"experiment already exists; use resume: {experiment_id}"
                )
            stored_lock = ProtocolLock.model_validate(existing["protocol_lock"])
            if stored_lock.protocol_sha256 != canonical_sha256(protocol):
                raise StoreConflictError("resume protocol differs from immutable protocol lock")
            capabilities = CapabilitySnapshot.model_validate(stored_lock.capability_snapshot)
            return capabilities, stored_lock
        if resume:
            raise KeyError(f"experiment does not exist: {experiment_id}")

        parent_id = protocol.experiment.parent_experiment_id
        if parent_id is not None:
            try:
                self.repository.get_experiment(parent_id)
            except KeyError as exc:
                raise ProtocolCompatibilityError(
                    f"parent experiment does not exist: {parent_id}"
                ) from exc

        self.synchronizer.sync()
        capabilities = self.repository.get_latest_capabilities()
        self._validate_resources(protocol, capabilities)
        lock = build_protocol_lock(
            protocol,
            capabilities,
            repository_dir=self.repository_dir,
            dependency_lock_path=self.dependency_lock_path,
        )
        lock_path = self.workspace_dir / "experiments" / experiment_id / "protocol.lock.yaml"
        lock = write_protocol_lock(lock_path, lock)
        self.repository.create_experiment(
            experiment_id,
            protocol.model_dump(mode="json", by_alias=True, exclude_none=True),
            lock.model_dump(mode="json", by_alias=True, exclude_none=True),
            parent_experiment_id=protocol.experiment.parent_experiment_id,
        )
        return capabilities, lock

    def _validate_resources(
        self,
        protocol: ExperimentProtocol,
        capabilities: CapabilitySnapshot,
    ) -> None:
        resources = protocol.resources
        refs = [
            ("scene", resources.scene),
            ("robot", resources.robot),
            ("controller", resources.controller),
        ]
        if resources.policy is not None:
            refs.append(("policy", resources.policy))
        for kind, ref in refs:
            entry = self.repository.get_registry_entry(kind, ref.id, ref.revision)
            if entry.status not in {None, "READY"}:
                raise ProtocolCompatibilityError(
                    f"resource is not ready: {kind} {ref.id}@{ref.revision} ({entry.status})"
                )
        if (
            capabilities.limits.maximum_episode_duration_s is not None
            and protocol.execution.maximum_duration_s
            > capabilities.limits.maximum_episode_duration_s
        ):
            raise ProtocolCompatibilityError("requested rollout duration exceeds Server limit")

    def _initialize_method(
        self,
        protocol: ExperimentProtocol,
        capabilities: CapabilitySnapshot,
    ) -> tuple[FailureDiscoveryMethod, str]:
        method = self.method_registry.create(protocol.method.plugin_id, protocol.method.config)
        if method.plugin_version != protocol.method.plugin_version:
            raise ProtocolCompatibilityError(
                f"method version lock requires {protocol.method.plugin_version}; "
                f"installed={method.plugin_version}"
            )
        compatibility = check_method_compatibility(method.requirements(), capabilities)
        if not compatibility.compatible:
            messages = "; ".join(issue.message for issue in compatibility.issues)
            raise ProtocolCompatibilityError(f"method is incompatible with Server: {messages}")
        scene = self.synchronizer.require_scene_snapshot(protocol.resources.scene)
        world_model = WorldModelProjector().project(
            task=protocol.task,
            resources=protocol.resources,
            scene=scene,
            capabilities=capabilities,
        )
        method_instance_id = f"{protocol.method.plugin_id}:{protocol.experiment.experiment_id}"
        method.initialize(
            MethodContext(
                experiment_id=protocol.experiment.experiment_id,
                method_instance_id=method_instance_id,
                master_seed=protocol.execution.master_seed,
                world_model=world_model,
                capabilities=capabilities,
            )
        )
        checkpoint = self.repository.load_latest_method_checkpoint(
            protocol.experiment.experiment_id,
            method_instance_id,
        )
        if checkpoint is not None:
            method.load_state_dict(checkpoint)
        return method, method_instance_id

    def _resume_pending(
        self,
        protocol: ExperimentProtocol,
        definition: FailureDefinition,
        method: FailureDiscoveryMethod,
        method_instance_id: str,
        maximum_parallel: int,
    ) -> None:
        pending = self.repository.list_candidates(
            protocol.experiment.experiment_id,
            include_observed=False,
        )
        if pending:
            self._process_candidates(
                protocol,
                definition,
                method,
                method_instance_id,
                pending,
                maximum_parallel,
            )

    def _process_candidates(
        self,
        protocol: ExperimentProtocol,
        definition: FailureDefinition,
        method: FailureDiscoveryMethod,
        method_instance_id: str,
        records: list[CandidateRecord],
        maximum_parallel: int,
    ) -> None:
        valid_records: list[CandidateRecord] = []
        for record in records:
            if not record.validation.valid:
                observation = CandidateObservation(
                    candidate_id=record.candidate_id,
                    status="VALIDATION_REJECTED",
                    details={
                        "issues": [
                            item.model_dump(mode="json")
                            for item in record.validation.issues
                        ]
                    },
                )
                self._observe_atomically(
                    protocol,
                    method,
                    method_instance_id,
                    record,
                    observation,
                )
            else:
                valid_records.append(record)

        tasks: list[tuple[CandidateRecord, RolloutAttemptRecord]] = []
        for record in valid_records:
            self.repository.mark_candidate_state(
                protocol.experiment.experiment_id,
                record.candidate_id,
                CandidateState.RUNNING,
            )
            for repeat_index in range(protocol.execution.repeats_per_candidate):
                request = _rollout_request(protocol, record, repeat_index)
                attempt = self.coordinator.prepare(
                    experiment_id=protocol.experiment.experiment_id,
                    candidate_id=record.candidate_id,
                    repeat_index=repeat_index,
                    request=request,
                )
                tasks.append((record, attempt))

        terminal: dict[str, RolloutAttemptRecord] = {}
        for start in range(0, len(tasks), maximum_parallel):
            chunk = tasks[start : start + maximum_parallel]
            terminal.update(self._drive_attempts([attempt for _, attempt in chunk]))

        for record in valid_records:
            attempts = [attempt for candidate, attempt in tasks if candidate == record]
            final_attempts = [terminal[attempt.attempt_id] for attempt in attempts]
            observation = self._evaluate_candidate(protocol, definition, record, final_attempts)
            self._observe_atomically(
                protocol,
                method,
                method_instance_id,
                record,
                observation,
            )

    def _drive_attempts(
        self,
        attempts: list[RolloutAttemptRecord],
    ) -> dict[str, RolloutAttemptRecord]:
        pending = {item.attempt_id for item in attempts}
        terminal: dict[str, RolloutAttemptRecord] = {}
        cycles = 0
        while pending:
            for attempt_id in list(pending):
                record = self.coordinator.advance(attempt_id)
                if _attempt_is_terminal(record):
                    pending.remove(attempt_id)
                    terminal[attempt_id] = record
            if not pending:
                break
            cycles += 1
            if self.max_poll_cycles is not None and cycles >= self.max_poll_cycles:
                raise TimeoutError(f"rollout polling exceeded {self.max_poll_cycles} cycles")
            self._sleep(self.poll_interval_s)
        return terminal

    def _evaluate_candidate(
        self,
        protocol: ExperimentProtocol,
        definition: FailureDefinition,
        candidate: CandidateRecord,
        attempts: list[RolloutAttemptRecord],
    ) -> CandidateObservation:
        evaluations = []
        execution_errors: list[dict[str, object]] = []
        for attempt in attempts:
            if attempt.result is None:
                execution_errors.append(
                    {
                        "attempt_id": attempt.attempt_id,
                        "state": attempt.state,
                        "error": attempt.error,
                    }
                )
                continue
            evaluation = self.evaluator.evaluate(
                experiment_id=protocol.experiment.experiment_id,
                attempt_id=attempt.attempt_id,
                candidate_id=candidate.candidate_id,
                repeat_index=attempt.repeat_index,
                definition=definition,
                result=attempt.result,
            )
            evaluations.append(self.repository.save_evaluation(evaluation))
            self.repository.mark_evaluated(attempt.attempt_id)

        if not evaluations:
            self.repository.mark_candidate_state(
                protocol.experiment.experiment_id,
                candidate.candidate_id,
                CandidateState.EXECUTION_ERROR,
            )
            return CandidateObservation(
                candidate_id=candidate.candidate_id,
                status="EXECUTION_ERROR",
                details={"attempts": execution_errors},
            )

        archive = self.archive.refresh(
            protocol.experiment.experiment_id,
            candidate.candidate_id,
            canonical_sha256(definition),
        )
        all_indeterminate = all(
            item.outcome == EvaluationOutcome.INDETERMINATE for item in evaluations
        )
        self.repository.mark_candidate_state(
            protocol.experiment.experiment_id,
            candidate.candidate_id,
            CandidateState.EVALUATED,
        )
        objectives = {
            name: minimum
            for name, minimum in archive.objective_minima.items()
        }
        return CandidateObservation(
            candidate_id=candidate.candidate_id,
            status="INDETERMINATE" if all_indeterminate else "EVALUATED",
            failure=archive.confirmed_failure if archive.valid_repeat_count else None,
            objectives=objectives,
            details={
                "valid_repeats": archive.valid_repeat_count,
                "indeterminate_repeats": archive.indeterminate_count,
                "execution_errors": execution_errors,
            },
        )

    def _observe_atomically(
        self,
        protocol: ExperimentProtocol,
        method: FailureDiscoveryMethod,
        method_instance_id: str,
        candidate: CandidateRecord,
        observation: CandidateObservation,
    ) -> None:
        method.observe([observation])
        self.repository.checkpoint_and_mark_observed(
            experiment_id=protocol.experiment.experiment_id,
            method_instance_id=method_instance_id,
            candidate_id=candidate.candidate_id,
            state=method.state_dict(),
        )


def _failure_definition(protocol: ExperimentProtocol) -> FailureDefinition:
    payload = dict(protocol.failure_definition.config)
    payload["definition_id"] = protocol.failure_definition.definition_id
    payload["definition_version"] = protocol.failure_definition.version
    return FailureDefinition.model_validate(payload)


def _maximum_parallel(
    protocol: ExperimentProtocol,
    capabilities: CapabilitySnapshot,
) -> int:
    server_limit = capabilities.limits.maximum_parallel_jobs
    requested = protocol.execution.maximum_parallel_jobs
    return min(requested, server_limit) if server_limit is not None else requested


def _rollout_request(
    protocol: ExperimentProtocol,
    candidate: CandidateRecord,
    repeat_index: int,
) -> RolloutRequest:
    experiment_id = protocol.experiment.experiment_id
    candidate_id = candidate.candidate_id
    video_policy = protocol.artifacts.video
    return RolloutRequest(
        client_request_id=f"{experiment_id}:{candidate_id}:{repeat_index}",
        research_context=ResearchContext(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            method_instance_id=candidate.method_instance_id,
            opaque_tags=[f"repeat:{repeat_index}"],
        ),
        resources=protocol.resources,
        task=protocol.task,
        interventions=candidate.candidate.interventions,
        execution=ExecutionSpec(
            seed=derive_repeat_seed(
                protocol.execution.master_seed,
                candidate.candidate_sha256,
                repeat_index,
                version=protocol.execution.seed_policy,
            ),
            maximum_duration_s=protocol.execution.maximum_duration_s,
        ),
        recording=RecordingSpec(
            state_trajectory=protocol.artifacts.trajectory == "always",
            action_trajectory=protocol.artifacts.trajectory == "always",
            contact_events=protocol.artifacts.events == "always",
            policy_trace=protocol.artifacts.policy_trace == "always",
            video=video_policy,
        ),
    )


def _attempt_is_terminal(record: RolloutAttemptRecord) -> bool:
    return record.state in {
        RolloutAttemptState.INGESTED,
        RolloutAttemptState.EVALUATED,
        RolloutAttemptState.REMOTE_FAILED,
        RolloutAttemptState.INFRASTRUCTURE_ERROR,
        RolloutAttemptState.CANCELLED,
    }
