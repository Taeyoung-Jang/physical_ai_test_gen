"""SQLite persistence for experiments and durable remote rollout attempts."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterator

from pydantic import Field

from failure_client.candidates import BuiltCandidate, CandidateValidationResult
from failure_client.contracts import (
    ArtifactRef,
    CapabilitySnapshot,
    ContractModel,
    LocalArtifact,
    RegistryEntry,
    RegistrySnapshot,
    RemoteJobState,
    RolloutRequest,
    RolloutResult,
    SceneQueryRequest,
    SceneQueryResult,
    SceneSnapshot,
    canonical_json,
    canonical_sha256,
)
from failure_client.evaluation import ResearchEvaluation


class ExperimentState(StrEnum):
    CREATED = "CREATED"
    VALIDATING_PROTOCOL = "VALIDATING_PROTOCOL"
    RUNNING_SEARCH = "RUNNING_SEARCH"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RolloutAttemptState(StrEnum):
    SUBMIT_PENDING = "SUBMIT_PENDING"
    SUBMITTED = "SUBMITTED"
    REMOTE_RUNNING = "REMOTE_RUNNING"
    RESULT_AVAILABLE = "RESULT_AVAILABLE"
    DOWNLOADING_ARTIFACTS = "DOWNLOADING_ARTIFACTS"
    INGESTED = "INGESTED"
    EVALUATED = "EVALUATED"
    RETRY_PENDING = "RETRY_PENDING"
    REMOTE_FAILED = "REMOTE_FAILED"
    INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELLED = "CANCELLED"


class CandidateState(StrEnum):
    PROPOSED = "PROPOSED"
    VALIDATION_REJECTED = "VALIDATION_REJECTED"
    RUNNING = "RUNNING"
    EVALUATED = "EVALUATED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    OBSERVED = "OBSERVED"


class CandidateRecord(ContractModel):
    experiment_id: str
    candidate_id: str
    method_instance_id: str
    candidate_sha256: str
    candidate: BuiltCandidate
    validation: CandidateValidationResult
    state: CandidateState
    created_at: datetime
    updated_at: datetime


class RolloutAttemptRecord(ContractModel):
    attempt_id: str
    experiment_id: str
    candidate_id: str
    repeat_index: int = Field(ge=0)
    idempotency_key: str
    request_sha256: str
    request: RolloutRequest
    job_id: str | None = None
    state: RolloutAttemptState
    remote_status: RemoteJobState | None = None
    result: RolloutResult | None = None
    result_sha256: str | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class StoreConflictError(RuntimeError):
    pass


class ClientRepository:
    """Small transactional repository; one connection is opened per operation."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def create_experiment(
        self,
        experiment_id: str,
        protocol: dict[str, Any],
        protocol_lock: dict[str, Any],
        *,
        parent_experiment_id: str | None = None,
    ) -> None:
        now = _now()
        with self.transaction() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO experiments (
                        experiment_id, parent_experiment_id, state,
                        protocol_json, protocol_lock_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        parent_experiment_id,
                        ExperimentState.CREATED,
                        _json(protocol),
                        _json(protocol_lock),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise StoreConflictError(f"experiment already exists: {experiment_id}") from exc

    def set_experiment_state(self, experiment_id: str, state: ExperimentState) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                "UPDATE experiments SET state = ?, updated_at = ? WHERE experiment_id = ?",
                (state, _now(), experiment_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(experiment_id)

    def get_experiment(self, experiment_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            raise KeyError(experiment_id)
        return {
            "experiment_id": row["experiment_id"],
            "parent_experiment_id": row["parent_experiment_id"],
            "state": ExperimentState(row["state"]),
            "protocol": json.loads(row["protocol_json"]),
            "protocol_lock": json.loads(row["protocol_lock_json"]),
            "created_at": datetime.fromisoformat(row["created_at"]),
            "updated_at": datetime.fromisoformat(row["updated_at"]),
        }

    def store_registry_snapshot(
        self,
        capabilities: CapabilitySnapshot,
        registry: RegistrySnapshot,
    ) -> None:
        if capabilities.registry_revision != registry.registry_revision:
            raise StoreConflictError(
                "capability and registry snapshots refer to different registry revisions"
            )
        collections = {
            "scene": registry.scenes,
            "robot": registry.robots,
            "controller": registry.controllers,
            "policy": registry.policies,
            "task": registry.tasks,
        }
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO registry_syncs (
                    registry_revision, capability_json, registry_json, synced_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(registry_revision) DO UPDATE SET
                    capability_json = excluded.capability_json,
                    registry_json = excluded.registry_json,
                    synced_at = excluded.synced_at
                """,
                (
                    registry.registry_revision,
                    canonical_json(capabilities).decode("utf-8"),
                    canonical_json(registry).decode("utf-8"),
                    _now(),
                ),
            )
            for kind, entries in collections.items():
                connection.execute(
                    "UPDATE registry_entries SET is_latest = 0 WHERE kind = ?",
                    (kind,),
                )
                for entry in entries:
                    connection.execute(
                        """
                        INSERT INTO registry_entries (
                            kind, resource_id, revision, status,
                            payload_json, is_latest, last_seen_at
                        ) VALUES (?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT(kind, resource_id, revision) DO UPDATE SET
                            status = excluded.status,
                            payload_json = excluded.payload_json,
                            is_latest = 1,
                            last_seen_at = excluded.last_seen_at
                        """,
                        (
                            kind,
                            entry.id,
                            entry.revision,
                            entry.status,
                            canonical_json(entry).decode("utf-8"),
                            _now(),
                        ),
                    )

    def get_latest_capabilities(self) -> CapabilitySnapshot:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT capability_json FROM registry_syncs ORDER BY synced_at DESC LIMIT 1"
            ).fetchone()
        if row is None:
            raise KeyError("capability snapshot")
        return CapabilitySnapshot.model_validate_json(row["capability_json"])

    def get_registry_entry(
        self,
        kind: str,
        resource_id: str,
        revision: str | None = None,
    ) -> RegistryEntry:
        with self._connect() as connection:
            if revision is None:
                row = connection.execute(
                    """
                    SELECT payload_json FROM registry_entries
                    WHERE kind = ? AND resource_id = ? AND is_latest = 1
                    """,
                    (kind, resource_id),
                ).fetchone()
            else:
                row = connection.execute(
                    """
                    SELECT payload_json FROM registry_entries
                    WHERE kind = ? AND resource_id = ? AND revision = ?
                    """,
                    (kind, resource_id, revision),
                ).fetchone()
        if row is None:
            raise KeyError((kind, resource_id, revision))
        return RegistryEntry.model_validate_json(row["payload_json"])

    def store_scene_snapshot(self, snapshot: SceneSnapshot) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO scene_snapshots (
                    scene_id, revision, payload_json, fetched_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(scene_id, revision) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    snapshot.scene_id,
                    snapshot.scene_revision,
                    canonical_json(snapshot).decode("utf-8"),
                    _now(),
                ),
            )

    def get_scene_snapshot(self, scene_id: str, revision: str) -> SceneSnapshot:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM scene_snapshots
                WHERE scene_id = ? AND revision = ?
                """,
                (scene_id, revision),
            ).fetchone()
        if row is None:
            raise KeyError((scene_id, revision))
        return SceneSnapshot.model_validate_json(row["payload_json"])

    def store_scene_query_result(
        self,
        request: SceneQueryRequest,
        result: SceneQueryResult,
    ) -> None:
        request_hash = canonical_sha256(request)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO scene_query_results (
                    request_sha256, scene_id, revision, query_id,
                    request_json, result_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(request_sha256) DO UPDATE SET
                    result_json = excluded.result_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    request_hash,
                    request.scene.id,
                    request.scene.revision,
                    request.query_id,
                    canonical_json(request).decode("utf-8"),
                    canonical_json(result).decode("utf-8"),
                    _now(),
                ),
            )

    def get_scene_query_result(self, request: SceneQueryRequest) -> SceneQueryResult:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT result_json FROM scene_query_results WHERE request_sha256 = ?",
                (canonical_sha256(request),),
            ).fetchone()
        if row is None:
            raise KeyError(canonical_sha256(request))
        return SceneQueryResult.model_validate_json(row["result_json"])

    def create_rollout_attempt(
        self,
        *,
        experiment_id: str,
        candidate_id: str,
        repeat_index: int,
        request: RolloutRequest,
    ) -> RolloutAttemptRecord:
        request_sha256 = canonical_sha256(request)
        attempt_id = f"attempt_{uuid.uuid4().hex}"
        idempotency_key = str(uuid.uuid4())
        now = _now()
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO rollout_attempts (
                    attempt_id, experiment_id, candidate_id, repeat_index,
                    idempotency_key, request_sha256, request_json, state,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    experiment_id,
                    candidate_id,
                    repeat_index,
                    idempotency_key,
                    request_sha256,
                    canonical_json(request).decode("utf-8"),
                    RolloutAttemptState.SUBMIT_PENDING,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM rollout_attempts
                WHERE experiment_id = ? AND candidate_id = ? AND repeat_index = ?
                """,
                (experiment_id, candidate_id, repeat_index),
            ).fetchone()
        if row is None:
            raise AssertionError("rollout attempt insert did not return a row")
        record = _attempt_from_row(row)
        if record.request_sha256 != request_sha256:
            raise StoreConflictError(
                "candidate repeat already exists with a different canonical rollout request"
            )
        return record

    def save_candidate(
        self,
        *,
        experiment_id: str,
        candidate: BuiltCandidate,
        validation: CandidateValidationResult,
    ) -> CandidateRecord:
        candidate_sha = candidate.canonical_sha256
        now = _now()
        state = (
            CandidateState.PROPOSED
            if validation.valid
            else CandidateState.VALIDATION_REJECTED
        )
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO candidates (
                    experiment_id, candidate_id, method_instance_id,
                    candidate_sha256, candidate_json, validation_json,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    candidate.proposal.candidate_id,
                    candidate.proposal.method_instance_id,
                    candidate_sha,
                    canonical_json(candidate).decode("utf-8"),
                    canonical_json(validation).decode("utf-8"),
                    state,
                    now,
                    now,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM candidates
                WHERE experiment_id = ? AND candidate_id = ?
                """,
                (experiment_id, candidate.proposal.candidate_id),
            ).fetchone()
        if row is None:
            raise AssertionError("candidate insert did not return a row")
        record = _candidate_from_row(row)
        if record.candidate_sha256 != candidate_sha:
            raise StoreConflictError(
                "candidate ID already exists with different canonical content: "
                f"{candidate.proposal.candidate_id}"
            )
        return record

    def save_candidate_batch_with_checkpoint(
        self,
        *,
        experiment_id: str,
        method_instance_id: str,
        candidates: list[tuple[BuiltCandidate, CandidateValidationResult]],
        method_state: dict[str, Any],
    ) -> list[CandidateRecord]:
        """Atomically commit proposed candidates and the RNG/sequence cursor that made them."""

        now = _now()
        rows: list[sqlite3.Row] = []
        with self.transaction() as connection:
            for candidate, validation in candidates:
                candidate_sha = candidate.canonical_sha256
                state = (
                    CandidateState.PROPOSED
                    if validation.valid
                    else CandidateState.VALIDATION_REJECTED
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO candidates (
                        experiment_id, candidate_id, method_instance_id,
                        candidate_sha256, candidate_json, validation_json,
                        state, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        experiment_id,
                        candidate.proposal.candidate_id,
                        candidate.proposal.method_instance_id,
                        candidate_sha,
                        canonical_json(candidate).decode("utf-8"),
                        canonical_json(validation).decode("utf-8"),
                        state,
                        now,
                        now,
                    ),
                )
                row = connection.execute(
                    """
                    SELECT * FROM candidates
                    WHERE experiment_id = ? AND candidate_id = ?
                    """,
                    (experiment_id, candidate.proposal.candidate_id),
                ).fetchone()
                if row is None:
                    raise AssertionError("candidate insert did not return a row")
                if row["candidate_sha256"] != candidate_sha:
                    raise StoreConflictError(
                        "candidate ID already exists with different canonical interventions: "
                        f"{candidate.proposal.candidate_id}"
                    )
                rows.append(row)

            sequence_row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence
                FROM method_checkpoints
                WHERE experiment_id = ? AND method_instance_id = ?
                """,
                (experiment_id, method_instance_id),
            ).fetchone()
            sequence = int(sequence_row["next_sequence"])
            connection.execute(
                """
                INSERT INTO method_checkpoints (
                    experiment_id, method_instance_id, sequence,
                    state_json, state_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    method_instance_id,
                    sequence,
                    _json(method_state),
                    canonical_sha256(method_state),
                    _now(),
                ),
            )
        return [_candidate_from_row(row) for row in rows]

    def list_candidates(
        self,
        experiment_id: str,
        *,
        include_observed: bool = True,
    ) -> list[CandidateRecord]:
        with self._connect() as connection:
            if include_observed:
                rows = connection.execute(
                    """
                    SELECT * FROM candidates
                    WHERE experiment_id = ? ORDER BY created_at, candidate_id
                    """,
                    (experiment_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM candidates
                    WHERE experiment_id = ? AND state != ?
                    ORDER BY created_at, candidate_id
                    """,
                    (experiment_id, CandidateState.OBSERVED),
                ).fetchall()
        return [_candidate_from_row(row) for row in rows]

    def mark_candidate_state(
        self,
        experiment_id: str,
        candidate_id: str,
        state: CandidateState,
    ) -> None:
        with self.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE candidates SET state = ?, updated_at = ?
                WHERE experiment_id = ? AND candidate_id = ?
                """,
                (state, _now(), experiment_id, candidate_id),
            )
            if cursor.rowcount != 1:
                raise KeyError((experiment_id, candidate_id))

    def save_method_checkpoint(
        self,
        experiment_id: str,
        method_instance_id: str,
        state: dict[str, Any],
    ) -> int:
        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence
                FROM method_checkpoints
                WHERE experiment_id = ? AND method_instance_id = ?
                """,
                (experiment_id, method_instance_id),
            ).fetchone()
            sequence = int(row["next_sequence"])
            connection.execute(
                """
                INSERT INTO method_checkpoints (
                    experiment_id, method_instance_id, sequence,
                    state_json, state_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    method_instance_id,
                    sequence,
                    _json(state),
                    canonical_sha256(state),
                    _now(),
                ),
            )
        return sequence

    def checkpoint_and_mark_observed(
        self,
        *,
        experiment_id: str,
        method_instance_id: str,
        candidate_id: str,
        state: dict[str, Any],
    ) -> int:
        """Atomically persist method observation state and candidate consumption."""

        with self.transaction() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), -1) + 1 AS next_sequence
                FROM method_checkpoints
                WHERE experiment_id = ? AND method_instance_id = ?
                """,
                (experiment_id, method_instance_id),
            ).fetchone()
            sequence = int(row["next_sequence"])
            connection.execute(
                """
                INSERT INTO method_checkpoints (
                    experiment_id, method_instance_id, sequence,
                    state_json, state_sha256, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_id,
                    method_instance_id,
                    sequence,
                    _json(state),
                    canonical_sha256(state),
                    _now(),
                ),
            )
            cursor = connection.execute(
                """
                UPDATE candidates SET state = ?, updated_at = ?
                WHERE experiment_id = ? AND candidate_id = ?
                """,
                (
                    CandidateState.OBSERVED,
                    _now(),
                    experiment_id,
                    candidate_id,
                ),
            )
            if cursor.rowcount != 1:
                raise KeyError((experiment_id, candidate_id))
        return sequence

    def load_latest_method_checkpoint(
        self,
        experiment_id: str,
        method_instance_id: str,
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT state_json FROM method_checkpoints
                WHERE experiment_id = ? AND method_instance_id = ?
                ORDER BY sequence DESC LIMIT 1
                """,
                (experiment_id, method_instance_id),
            ).fetchone()
        return json.loads(row["state_json"]) if row is not None else None

    def save_evaluation(self, evaluation: ResearchEvaluation) -> ResearchEvaluation:
        """Append an evaluation, returning the immutable existing row on replay."""

        payload = canonical_json(evaluation).decode("utf-8")
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO evaluations (
                    evaluation_id, experiment_id, attempt_id, candidate_id,
                    repeat_index, evaluator_id, evaluator_version,
                    definition_id, definition_version, definition_sha256,
                    result_sha256, outcome, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evaluation.evaluation_id,
                    evaluation.experiment_id,
                    evaluation.attempt_id,
                    evaluation.candidate_id,
                    evaluation.repeat_index,
                    evaluation.evaluator_id,
                    evaluation.evaluator_version,
                    evaluation.definition_id,
                    evaluation.definition_version,
                    evaluation.definition_sha256,
                    evaluation.result_sha256,
                    evaluation.outcome,
                    payload,
                    evaluation.created_at.isoformat(),
                ),
            )
            row = connection.execute(
                "SELECT payload_json FROM evaluations WHERE evaluation_id = ?",
                (evaluation.evaluation_id,),
            ).fetchone()
        if row is None:
            raise AssertionError("evaluation insert did not return a row")
        stored = ResearchEvaluation.model_validate_json(row["payload_json"])
        semantic_fields = (
            "experiment_id",
            "attempt_id",
            "candidate_id",
            "repeat_index",
            "evaluator_id",
            "evaluator_version",
            "definition_sha256",
            "result_sha256",
            "outcome",
            "failure",
        )
        if any(getattr(stored, name) != getattr(evaluation, name) for name in semantic_fields):
            raise StoreConflictError(
                f"evaluation ID collision with different semantics: {evaluation.evaluation_id}"
            )
        return stored

    def list_evaluations(
        self,
        *,
        experiment_id: str,
        candidate_id: str | None = None,
        definition_sha256: str | None = None,
    ) -> list[ResearchEvaluation]:
        clauses = ["experiment_id = ?"]
        parameters: list[Any] = [experiment_id]
        if candidate_id is not None:
            clauses.append("candidate_id = ?")
            parameters.append(candidate_id)
        if definition_sha256 is not None:
            clauses.append("definition_sha256 = ?")
            parameters.append(definition_sha256)
        where = " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM evaluations WHERE {where} "  # noqa: S608
                "ORDER BY candidate_id, repeat_index, created_at",
                parameters,
            ).fetchall()
        return [ResearchEvaluation.model_validate_json(row["payload_json"]) for row in rows]

    def save_failure_case(self, record: Any) -> None:
        """Upsert the derived archive projection; source evaluations stay immutable."""

        from failure_client.archive.models import FailureCaseRecord

        validated = FailureCaseRecord.model_validate(record)
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO failure_cases (
                    experiment_id, candidate_id, definition_sha256,
                    payload_json, confirmed_failure, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id, candidate_id, definition_sha256) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    confirmed_failure = excluded.confirmed_failure,
                    updated_at = excluded.updated_at
                """,
                (
                    validated.experiment_id,
                    validated.candidate_id,
                    validated.definition_sha256,
                    canonical_json(validated).decode("utf-8"),
                    int(validated.confirmed_failure),
                    validated.updated_at.isoformat(),
                ),
            )

    def get_failure_case(
        self,
        experiment_id: str,
        candidate_id: str,
        definition_sha256: str,
    ) -> Any:
        from failure_client.archive.models import FailureCaseRecord

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM failure_cases
                WHERE experiment_id = ? AND candidate_id = ? AND definition_sha256 = ?
                """,
                (experiment_id, candidate_id, definition_sha256),
            ).fetchone()
        if row is None:
            raise KeyError((experiment_id, candidate_id, definition_sha256))
        return FailureCaseRecord.model_validate_json(row["payload_json"])

    def list_failure_cases(
        self,
        experiment_id: str,
        *,
        definition_sha256: str | None = None,
        confirmed_only: bool = False,
    ) -> list[Any]:
        from failure_client.archive.models import FailureCaseRecord

        clauses = ["experiment_id = ?"]
        parameters: list[Any] = [experiment_id]
        if definition_sha256 is not None:
            clauses.append("definition_sha256 = ?")
            parameters.append(definition_sha256)
        if confirmed_only:
            clauses.append("confirmed_failure = 1")
        where = " AND ".join(clauses)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM failure_cases WHERE {where} "  # noqa: S608
                "ORDER BY candidate_id",
                parameters,
            ).fetchall()
        return [FailureCaseRecord.model_validate_json(row["payload_json"]) for row in rows]

    def list_artifacts(self, attempt_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT artifact_id, kind, format, size_bytes, sha256,
                       local_path, state, verified_at
                FROM artifacts WHERE attempt_id = ? ORDER BY artifact_id
                """,
                (attempt_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_rollout_attempt(self, attempt_id: str) -> RolloutAttemptRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM rollout_attempts WHERE attempt_id = ?",
                (attempt_id,),
            ).fetchone()
        if row is None:
            raise KeyError(attempt_id)
        return _attempt_from_row(row)

    def list_rollout_attempts(
        self,
        experiment_id: str,
        candidate_id: str | None = None,
    ) -> list[RolloutAttemptRecord]:
        with self._connect() as connection:
            if candidate_id is None:
                rows = connection.execute(
                    """
                    SELECT * FROM rollout_attempts
                    WHERE experiment_id = ? ORDER BY candidate_id, repeat_index
                    """,
                    (experiment_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM rollout_attempts
                    WHERE experiment_id = ? AND candidate_id = ?
                    ORDER BY repeat_index
                    """,
                    (experiment_id, candidate_id),
                ).fetchall()
        return [_attempt_from_row(row) for row in rows]

    def list_recoverable_attempts(self) -> list[RolloutAttemptRecord]:
        terminal = (
            RolloutAttemptState.EVALUATED,
            RolloutAttemptState.REMOTE_FAILED,
            RolloutAttemptState.INFRASTRUCTURE_ERROR,
            RolloutAttemptState.CANCELLED,
        )
        placeholders = ",".join("?" for _ in terminal)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM rollout_attempts WHERE state NOT IN ({placeholders}) ",  # noqa: S608
                terminal,
            ).fetchall()
        return [_attempt_from_row(row) for row in rows]

    def mark_submitted(self, attempt_id: str, job_id: str, status: RemoteJobState) -> None:
        self._update_attempt(
            attempt_id,
            state=RolloutAttemptState.SUBMITTED,
            job_id=job_id,
            remote_status=status,
            error_json=None,
        )

    def mark_remote_status(self, attempt_id: str, status: RemoteJobState) -> None:
        if status == RemoteJobState.CANCELLED:
            state = RolloutAttemptState.CANCELLED
        elif status in {RemoteJobState.FAILED, RemoteJobState.INTERRUPTED}:
            state = RolloutAttemptState.REMOTE_FAILED
        else:
            state = RolloutAttemptState.REMOTE_RUNNING
        self._update_attempt(attempt_id, state=state, remote_status=status)

    def save_result(self, attempt_id: str, result: RolloutResult) -> None:
        self._update_attempt(
            attempt_id,
            state=RolloutAttemptState.RESULT_AVAILABLE,
            remote_status=result.execution.status,
            result_json=canonical_json(result).decode("utf-8"),
            result_sha256=canonical_sha256(result),
            error_json=None,
        )

    def mark_downloading_artifacts(self, attempt_id: str) -> None:
        self._update_attempt(attempt_id, state=RolloutAttemptState.DOWNLOADING_ARTIFACTS)

    def mark_ingested(self, attempt_id: str) -> None:
        self._update_attempt(attempt_id, state=RolloutAttemptState.INGESTED)

    def mark_evaluated(self, attempt_id: str) -> None:
        self._update_attempt(attempt_id, state=RolloutAttemptState.EVALUATED)

    def mark_cancelled(self, attempt_id: str) -> None:
        self._update_attempt(attempt_id, state=RolloutAttemptState.CANCELLED)

    def mark_error(
        self,
        attempt_id: str,
        error: dict[str, Any],
        *,
        retryable: bool,
    ) -> None:
        state = (
            RolloutAttemptState.RETRY_PENDING
            if retryable
            else RolloutAttemptState.INFRASTRUCTURE_ERROR
        )
        self._update_attempt(attempt_id, state=state, error_json=_json(error))

    def record_artifact(
        self,
        attempt_id: str,
        remote: ArtifactRef,
        local: LocalArtifact,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                INSERT INTO artifacts (
                    artifact_id, attempt_id, kind, format, size_bytes,
                    sha256, remote_json, local_path, state, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'VERIFIED', ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    local_path = excluded.local_path,
                    state = excluded.state,
                    verified_at = excluded.verified_at
                """,
                (
                    remote.artifact_id,
                    attempt_id,
                    remote.kind,
                    remote.format,
                    local.size_bytes,
                    local.sha256,
                    canonical_json(remote).decode("utf-8"),
                    str(local.path),
                    _now(),
                ),
            )

    def _update_attempt(self, attempt_id: str, **values: Any) -> None:
        values["updated_at"] = _now()
        assignments = ", ".join(f"{column} = ?" for column in values)
        parameters = [
            value.value if isinstance(value, StrEnum) else value
            for value in values.values()
        ]
        parameters.append(attempt_id)
        with self.transaction() as connection:
            cursor = connection.execute(
                f"UPDATE rollout_attempts SET {assignments} WHERE attempt_id = ?",  # noqa: S608
                parameters,
            )
            if cursor.rowcount != 1:
                raise KeyError(attempt_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    parent_experiment_id TEXT,
                    state TEXT NOT NULL,
                    protocol_json TEXT NOT NULL,
                    protocol_lock_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS rollout_attempts (
                    attempt_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
                    idempotency_key TEXT NOT NULL UNIQUE,
                    request_sha256 TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    job_id TEXT UNIQUE,
                    state TEXT NOT NULL,
                    remote_status TEXT,
                    result_json TEXT,
                    result_sha256 TEXT,
                    error_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(experiment_id, candidate_id, repeat_index),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    attempt_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    format TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    remote_json TEXT NOT NULL,
                    local_path TEXT NOT NULL,
                    state TEXT NOT NULL,
                    verified_at TEXT NOT NULL,
                    FOREIGN KEY(attempt_id) REFERENCES rollout_attempts(attempt_id)
                );

                CREATE TABLE IF NOT EXISTS registry_syncs (
                    registry_revision TEXT PRIMARY KEY,
                    capability_json TEXT NOT NULL,
                    registry_json TEXT NOT NULL,
                    synced_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS registry_entries (
                    kind TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    status TEXT,
                    payload_json TEXT NOT NULL,
                    is_latest INTEGER NOT NULL CHECK(is_latest IN (0, 1)),
                    last_seen_at TEXT NOT NULL,
                    PRIMARY KEY(kind, resource_id, revision)
                );

                CREATE INDEX IF NOT EXISTS idx_registry_entries_latest
                    ON registry_entries(kind, resource_id, is_latest);

                CREATE TABLE IF NOT EXISTS scene_snapshots (
                    scene_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(scene_id, revision)
                );

                CREATE TABLE IF NOT EXISTS scene_query_results (
                    request_sha256 TEXT PRIMARY KEY,
                    scene_id TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    query_id TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS method_checkpoints (
                    experiment_id TEXT NOT NULL,
                    method_instance_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    state_json TEXT NOT NULL,
                    state_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(experiment_id, method_instance_id, sequence),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );

                CREATE TABLE IF NOT EXISTS candidates (
                    experiment_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    method_instance_id TEXT NOT NULL,
                    candidate_sha256 TEXT NOT NULL,
                    candidate_json TEXT NOT NULL,
                    validation_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(experiment_id, candidate_id),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_id TEXT PRIMARY KEY,
                    experiment_id TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    repeat_index INTEGER NOT NULL CHECK(repeat_index >= 0),
                    evaluator_id TEXT NOT NULL,
                    evaluator_version TEXT NOT NULL,
                    definition_id TEXT NOT NULL,
                    definition_version TEXT NOT NULL,
                    definition_sha256 TEXT NOT NULL,
                    result_sha256 TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(
                        attempt_id, evaluator_id, evaluator_version,
                        definition_sha256, result_sha256
                    ),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id),
                    FOREIGN KEY(attempt_id) REFERENCES rollout_attempts(attempt_id)
                );

                CREATE INDEX IF NOT EXISTS idx_evaluations_candidate
                    ON evaluations(experiment_id, candidate_id, definition_sha256);

                CREATE TABLE IF NOT EXISTS failure_cases (
                    experiment_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL,
                    definition_sha256 TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    confirmed_failure INTEGER NOT NULL CHECK(confirmed_failure IN (0, 1)),
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(experiment_id, candidate_id, definition_sha256),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );

                PRAGMA user_version = 5;
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(rollout_attempts)").fetchall()
            }
            if "result_sha256" not in columns:
                connection.execute(
                    "ALTER TABLE rollout_attempts ADD COLUMN result_sha256 TEXT"
                )
            connection.execute("PRAGMA user_version = 6")


def _attempt_from_row(row: sqlite3.Row) -> RolloutAttemptRecord:
    return RolloutAttemptRecord(
        attempt_id=row["attempt_id"],
        experiment_id=row["experiment_id"],
        candidate_id=row["candidate_id"],
        repeat_index=row["repeat_index"],
        idempotency_key=row["idempotency_key"],
        request_sha256=row["request_sha256"],
        request=RolloutRequest.model_validate_json(row["request_json"]),
        job_id=row["job_id"],
        state=RolloutAttemptState(row["state"]),
        remote_status=RemoteJobState(row["remote_status"]) if row["remote_status"] else None,
        result=RolloutResult.model_validate_json(row["result_json"])
        if row["result_json"]
        else None,
        result_sha256=row["result_sha256"],
        error=json.loads(row["error_json"]) if row["error_json"] else None,
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _candidate_from_row(row: sqlite3.Row) -> CandidateRecord:
    return CandidateRecord(
        experiment_id=row["experiment_id"],
        candidate_id=row["candidate_id"],
        method_instance_id=row["method_instance_id"],
        candidate_sha256=row["candidate_sha256"],
        candidate=BuiltCandidate.model_validate_json(row["candidate_json"]),
        validation=CandidateValidationResult.model_validate_json(row["validation_json"]),
        state=CandidateState(row["state"]),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()
