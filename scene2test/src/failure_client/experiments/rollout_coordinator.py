"""Crash-recoverable orchestration for one remote rollout attempt."""

from __future__ import annotations

import time
from collections.abc import Callable

from failure_client.api import SimulationGateway
from failure_client.contracts import GatewayError, RemoteJobState, RolloutRequest
from failure_client.storage import (
    ClientRepository,
    RolloutAttemptRecord,
    RolloutAttemptState,
)


class RolloutCoordinator:
    def __init__(
        self,
        repository: ClientRepository,
        gateway: SimulationGateway,
        *,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        self._sleep = sleep

    def prepare(
        self,
        *,
        experiment_id: str,
        candidate_id: str,
        repeat_index: int,
        request: RolloutRequest,
    ) -> RolloutAttemptRecord:
        return self.repository.create_rollout_attempt(
            experiment_id=experiment_id,
            candidate_id=candidate_id,
            repeat_index=repeat_index,
            request=request,
        )

    def advance(self, attempt_id: str) -> RolloutAttemptRecord:
        record = self.repository.get_rollout_attempt(attempt_id)
        if record.state in {
            RolloutAttemptState.INGESTED,
            RolloutAttemptState.EVALUATED,
            RolloutAttemptState.REMOTE_FAILED,
            RolloutAttemptState.INFRASTRUCTURE_ERROR,
            RolloutAttemptState.CANCELLED,
        }:
            return record

        try:
            if record.job_id is None:
                accepted = self.gateway.submit_rollout(
                    record.request,
                    record.idempotency_key,
                )
                self.repository.mark_submitted(
                    record.attempt_id,
                    accepted.job_id,
                    accepted.status,
                )
                record = self.repository.get_rollout_attempt(attempt_id)

            if record.result is None:
                status = self.gateway.get_rollout_status(record.job_id or "")
                self.repository.mark_remote_status(attempt_id, status.status)
                if status.status != RemoteJobState.SUCCEEDED:
                    return self.repository.get_rollout_attempt(attempt_id)
                result = self.gateway.get_rollout_result(record.job_id or "")
                self.repository.save_result(attempt_id, result)
                record = self.repository.get_rollout_attempt(attempt_id)

            if record.result is None:
                raise AssertionError("result must be present before artifact ingestion")
            self.repository.mark_downloading_artifacts(attempt_id)
            for remote in record.result.artifacts:
                local = self.gateway.download_artifact(remote)
                self.repository.record_artifact(attempt_id, remote, local)
            self.repository.mark_ingested(attempt_id)
        except GatewayError as exc:
            self.repository.mark_error(
                attempt_id,
                {
                    "code": exc.code,
                    "message": str(exc),
                    "request_id": exc.request_id,
                },
                retryable=exc.retryable,
            )
        return self.repository.get_rollout_attempt(attempt_id)

    def wait_until_terminal(
        self,
        attempt_id: str,
        *,
        poll_interval_s: float = 1.0,
        max_polls: int | None = None,
    ) -> RolloutAttemptRecord:
        polls = 0
        while True:
            record = self.advance(attempt_id)
            if record.state in {
                RolloutAttemptState.INGESTED,
                RolloutAttemptState.EVALUATED,
                RolloutAttemptState.REMOTE_FAILED,
                RolloutAttemptState.INFRASTRUCTURE_ERROR,
                RolloutAttemptState.CANCELLED,
            }:
                return record
            polls += 1
            if max_polls is not None and polls >= max_polls:
                return record
            self._sleep(poll_interval_s)

    def recover_all(self) -> list[RolloutAttemptRecord]:
        recoverable = self.repository.list_recoverable_attempts()
        return [self.advance(record.attempt_id) for record in recoverable]

    def cancel(self, attempt_id: str) -> RolloutAttemptRecord:
        record = self.repository.get_rollout_attempt(attempt_id)
        if record.job_id is None:
            self.repository.mark_cancelled(attempt_id)
            return self.repository.get_rollout_attempt(attempt_id)
        result = self.gateway.cancel_rollout(record.job_id)
        self.repository.mark_remote_status(attempt_id, result.status)
        return self.repository.get_rollout_attempt(attempt_id)
