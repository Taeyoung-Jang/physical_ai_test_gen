from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from failure_client.contracts import (
    RemoteJobState,
    RolloutAccepted,
    RolloutJobStatus,
    RolloutRequest,
    RolloutResult,
    canonical_json,
    canonical_sha256,
)

from .config import ServerConfig


class JobError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.retryable = retryable


class JobStore:
    def __init__(self, config: ServerConfig) -> None:
        self.config = config
        self.db_path = config.data_root / "db/simulation_server.sqlite"
        self.output_root = config.data_root / "outputs/jobs"
        self._lock = threading.Lock()
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY, idempotency_key TEXT UNIQUE NOT NULL,
                    request_sha256 TEXT NOT NULL, request_json TEXT NOT NULL,
                    status TEXT NOT NULL, result_json TEXT, submitted_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL, process_id INTEGER
                )"""
            )
            db.execute(
                "UPDATE jobs SET status = 'INTERRUPTED', updated_at = ? "
                "WHERE status NOT IN ('SUCCEEDED','FAILED','CANCELLED','INTERRUPTED')",
                (datetime.now(UTC).isoformat(),),
            )

    def submit(self, request: RolloutRequest, idempotency_key: str) -> RolloutAccepted:
        request_hash = canonical_sha256(request)
        now = datetime.now(UTC)
        with self._lock, self._connect() as db:
            row = db.execute(
                "SELECT job_id, request_sha256, status, submitted_at FROM jobs "
                "WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row:
                if row[1] != request_hash:
                    raise JobError("IDEMPOTENCY_CONFLICT", "key was used for another request", 409)
                return RolloutAccepted(
                    job_id=row[0], status=row[2], request_sha256=row[1], submitted_at=row[3]
                )
            job_id = f"job_{uuid.uuid4().hex}"
            db.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, ?, NULL, ?, ?, NULL)",
                (
                    job_id,
                    idempotency_key,
                    request_hash,
                    canonical_json(request).decode(),
                    RemoteJobState.QUEUED,
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
        return RolloutAccepted(
            job_id=job_id,
            status=RemoteJobState.QUEUED,
            request_sha256=request_hash,
            submitted_at=now,
        )

    def run(self, job_id: str) -> None:
        row = self._row(job_id)
        if row[4] == RemoteJobState.CANCELLED:
            return
        job_dir = self.output_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        request_path = job_dir / "request.json"
        request_path.write_text(row[3], encoding="utf-8")
        command = [
            self.config.worker_python,
            "-m",
            "simulation_server.worker",
            "--request",
            str(request_path),
            "--output",
            str(job_dir),
            "--groot-root",
            str(self.config.groot_root),
            "--backend",
            self.config.execution_backend,
        ]
        self._set_status(job_id, RemoteJobState.INITIALIZING_RUNTIME)
        log_path = job_dir / "worker.log"
        try:
            with log_path.open("wb") as log:
                environment = os.environ.copy()
                source_root = str(Path(__file__).resolve().parents[1])
                existing_python_path = environment.get("PYTHONPATH")
                environment["PYTHONPATH"] = (
                    f"{source_root}{os.pathsep}{existing_python_path}"
                    if existing_python_path
                    else source_root
                )
                process = subprocess.Popen(
                    command,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=environment,
                )
                self._set_process(job_id, process.pid, RemoteJobState.RUNNING)
                timeout = (
                    json.loads(row[3])["execution"]["maximum_duration_s"]
                    + self.config.worker_startup_grace_s
                )
                return_code = process.wait(timeout=timeout)
            if return_code != 0:
                self._fail(job_id, "WORKER_EXIT_NONZERO", return_code)
                return
            result = RolloutResult.model_validate_json(
                (job_dir / "execution_result.json").read_text()
            )
            self._finish(job_id, result)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            self._fail(job_id, "WORKER_TIMEOUT", None)
        except Exception as exc:
            self._fail(job_id, f"WORKER_EXCEPTION:{type(exc).__name__}", None)

    def status(self, job_id: str) -> RolloutJobStatus:
        row = self._row(job_id)
        return RolloutJobStatus(job_id=job_id, status=row[4], updated_at=row[7])

    def result(self, job_id: str) -> RolloutResult:
        row = self._row(job_id)
        if row[5] is None:
            raise JobError("RESULT_NOT_READY", f"result for {job_id} is not ready", 409)
        return RolloutResult.model_validate_json(row[5])

    def cancel(self, job_id: str) -> RemoteJobState:
        row = self._row(job_id)
        if row[8]:
            try:
                import signal

                os.kill(row[8], signal.SIGTERM)
            except ProcessLookupError:
                pass
        self._set_status(job_id, RemoteJobState.CANCELLED)
        return RemoteJobState.CANCELLED

    def artifact_path(self, artifact_id: str) -> Path:
        try:
            job_id, name = artifact_id.split(":", 1)
        except ValueError as exc:
            raise JobError("ARTIFACT_NOT_FOUND", "artifact was not found", 404) from exc
        allowed = {
            "state_trajectory.jsonl",
            "action_trajectory.jsonl",
            "contacts.jsonl",
            "reproduction.json",
            "worker.log",
            "rollout.mp4",
            "rollout.gif",
            "thumbnail.png",
        }
        if name not in allowed:
            raise JobError("ARTIFACT_NOT_FOUND", "artifact was not found", 404)
        path = self.output_root / job_id / name
        if not path.is_file():
            raise JobError("ARTIFACT_NOT_FOUND", "artifact was not found", 404)
        return path

    def _fail(self, job_id: str, reason: str, return_code: int | None) -> None:
        from failure_client.contracts import ExecutionSummary

        result = RolloutResult(
            job_id=job_id,
            execution=ExecutionSummary(
                valid=False, status=RemoteJobState.FAILED, termination_reason=reason
            ),
            summary_metrics={"worker_return_code": return_code},
        )
        self._finish(job_id, result)

    def _finish(self, job_id: str, result: RolloutResult) -> None:
        with self._lock, self._connect() as db:
            current = db.execute("SELECT status FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if current and current[0] == RemoteJobState.CANCELLED:
                return
            db.execute(
                "UPDATE jobs SET status = ?, result_json = ?, updated_at = ?, "
                "process_id = NULL WHERE job_id = ?",
                (
                    result.execution.status,
                    result.model_dump_json(by_alias=True),
                    datetime.now(UTC).isoformat(),
                    job_id,
                ),
            )

    def _set_status(self, job_id: str, status: RemoteJobState) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, updated_at = ? WHERE job_id = ?",
                (status, datetime.now(UTC).isoformat(), job_id),
            )

    def _set_process(self, job_id: str, pid: int, status: RemoteJobState) -> None:
        with self._lock, self._connect() as db:
            db.execute(
                "UPDATE jobs SET status = ?, process_id = ?, updated_at = ? WHERE job_id = ?",
                (status, pid, datetime.now(UTC).isoformat(), job_id),
            )

    def _row(self, job_id: str) -> tuple:
        with self._connect() as db:
            row = db.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobError("JOB_NOT_FOUND", f"job {job_id} was not found", 404)
        return row

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)
