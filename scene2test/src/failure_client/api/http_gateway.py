"""HTTP adapter for the external RunPod simulation Server."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from failure_client.contracts import (
    ArtifactRef,
    CancelResult,
    CapabilitySnapshot,
    ContractValidationError,
    ErrorEnvelope,
    ErrorInfo,
    GatewayError,
    GatewayHTTPError,
    LocalArtifact,
    RegistrySnapshot,
    ResourceRef,
    RolloutAccepted,
    RolloutJobStatus,
    RolloutRequest,
    RolloutResult,
    SceneQueryRequest,
    SceneQueryResult,
    SceneSnapshot,
    canonical_json,
    canonical_sha256,
)

from .artifact_downloader import persist_verified_artifact
from .gateway import SimulationGateway

_ModelT = TypeVar("_ModelT", bound=BaseModel)
_RETRYABLE_STATUS = frozenset({408, 429, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class HttpGatewayConfig:
    base_url: str
    artifact_dir: Path
    bearer_token: str | None = None
    timeout_s: float = 30.0
    max_attempts: int = 3
    backoff_base_s: float = 0.25
    backoff_max_s: float = 5.0

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("base_url must not be empty")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.backoff_base_s < 0 or self.backoff_max_s < 0:
            raise ValueError("backoff values must be non-negative")


class HttpSimulationGateway(SimulationGateway):
    """Translate the logical Client contract to synchronous HTTP calls."""

    def __init__(
        self,
        config: HttpGatewayConfig,
        *,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleep
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_s,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpSimulationGateway:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_health(self) -> dict[str, Any]:
        response = self._request("GET", "/api/v1/health", expected={200})
        return self._json_object(response)

    def get_capabilities(self) -> CapabilitySnapshot:
        response = self._request("GET", "/api/v1/capabilities", expected={200})
        return self._parse_model(response, CapabilitySnapshot)

    def get_registry_snapshot(self) -> RegistrySnapshot:
        response = self._request("GET", "/api/v1/registry/snapshot", expected={200})
        return self._parse_model(response, RegistrySnapshot)

    def get_scene_snapshot(self, ref: ResourceRef) -> SceneSnapshot:
        scene_id = quote(ref.id, safe="")
        response = self._request(
            "GET",
            f"/api/v1/scenes/{scene_id}/snapshot",
            expected={200},
            params={"revision": ref.revision},
        )
        snapshot = self._parse_model(response, SceneSnapshot)
        if snapshot.scene_id != ref.id or snapshot.scene_revision != ref.revision:
            raise ContractValidationError(
                "scene snapshot does not match the requested revision",
                code="RESOURCE_REVISION_MISMATCH",
            )
        return snapshot

    def query_scene(self, request: SceneQueryRequest) -> SceneQueryResult:
        scene_id = quote(request.scene.id, safe="")
        response = self._request(
            "POST",
            f"/api/v1/scenes/{scene_id}/queries",
            expected={200},
            content=canonical_json(request),
            headers={"Content-Type": "application/json"},
        )
        result = self._parse_model(response, SceneQueryResult)
        if (
            result.scene != request.scene
            or result.query_id != request.query_id
        ):
            raise ContractValidationError(
                "scene query result does not match the request",
                code="QUERY_RESULT_MISMATCH",
            )
        return result

    def submit_rollout(
        self,
        request: RolloutRequest,
        idempotency_key: str,
    ) -> RolloutAccepted:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key must not be empty")
        response = self._request(
            "POST",
            "/api/v1/rollouts",
            expected={200, 202},
            content=canonical_json(request),
            headers={
                "Content-Type": "application/json",
                "Idempotency-Key": idempotency_key,
            },
        )
        accepted = self._parse_model(response, RolloutAccepted)
        expected_hash = canonical_sha256(request)
        if accepted.request_sha256 != expected_hash:
            raise ContractValidationError(
                "Server request hash does not match the submitted canonical payload",
                code="REQUEST_HASH_MISMATCH",
            )
        return accepted

    def get_rollout_status(self, job_id: str) -> RolloutJobStatus:
        response = self._request(
            "GET",
            f"/api/v1/rollouts/{quote(job_id, safe='')}",
            expected={200},
        )
        status = self._parse_model(response, RolloutJobStatus)
        self._require_job_id(job_id, status.job_id)
        return status

    def get_rollout_result(self, job_id: str) -> RolloutResult:
        response = self._request(
            "GET",
            f"/api/v1/rollouts/{quote(job_id, safe='')}/result",
            expected={200},
        )
        result = self._parse_model(response, RolloutResult)
        self._require_job_id(job_id, result.job_id)
        return result

    def cancel_rollout(self, job_id: str) -> CancelResult:
        response = self._request(
            "POST",
            f"/api/v1/rollouts/{quote(job_id, safe='')}/cancel",
            expected={200, 202},
        )
        result = self._parse_model(response, CancelResult)
        self._require_job_id(job_id, result.job_id)
        return result

    def download_artifact(self, ref: ArtifactRef) -> LocalArtifact:
        url = ref.download_url or f"/api/v1/artifacts/{quote(ref.artifact_id, safe='')}"
        response = self._request("GET", url, expected={200})
        return persist_verified_artifact(ref, response.content, self.config.artifact_dir)

    def _request(
        self,
        method: str,
        url: str,
        *,
        expected: set[int],
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        request_headers = self._authorization_headers(url)
        request_headers.update(headers or {})

        for attempt in range(1, self.config.max_attempts + 1):
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=request_headers,
                    timeout=self.config.timeout_s,
                    **kwargs,
                )
            except httpx.TransportError as exc:
                if attempt == self.config.max_attempts:
                    raise GatewayError(
                        f"Server transport failed after {attempt} attempts: {exc}",
                        code="SERVER_TRANSPORT_ERROR",
                        retryable=True,
                    ) from exc
                self._sleep(self._backoff_delay(attempt, None))
                continue

            if response.status_code in expected:
                return response
            if response.status_code in _RETRYABLE_STATUS and attempt < self.config.max_attempts:
                self._sleep(self._backoff_delay(attempt, response.headers.get("Retry-After")))
                continue
            raise self._http_error(response)

        raise AssertionError("unreachable retry loop")

    def _authorization_headers(self, url: str) -> dict[str, str]:
        if not self.config.bearer_token:
            return {}
        parsed = httpx.URL(url)
        if parsed.is_absolute_url:
            base = self._client.base_url
            if (parsed.scheme, parsed.host, parsed.port) != (base.scheme, base.host, base.port):
                return {}
        return {"Authorization": f"Bearer {self.config.bearer_token}"}

    def _backoff_delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after is not None:
            try:
                return min(max(float(retry_after), 0.0), self.config.backoff_max_s)
            except ValueError:
                pass
        base = min(self.config.backoff_base_s * (2 ** (attempt - 1)), self.config.backoff_max_s)
        return min(base + random.uniform(0.0, base * 0.1), self.config.backoff_max_s)

    def _http_error(self, response: httpx.Response) -> GatewayHTTPError:
        try:
            envelope = ErrorEnvelope.model_validate(response.json())
            info = envelope.error
        except (ValueError, ValidationError):
            info = ErrorInfo(
                code=f"HTTP_{response.status_code}",
                message=f"Server returned HTTP {response.status_code}",
                retryable=response.status_code in _RETRYABLE_STATUS,
                request_id=response.headers.get("X-Request-ID"),
            )
        if response.status_code in _RETRYABLE_STATUS and not info.retryable:
            info = info.model_copy(update={"retryable": True})
        return GatewayHTTPError(response.status_code, info)

    @staticmethod
    def _require_job_id(requested: str, returned: str) -> None:
        if requested != returned:
            raise ContractValidationError(
                f"Server returned job {returned!r} for request {requested!r}",
                code="JOB_ID_MISMATCH",
            )

    @staticmethod
    def _json_object(response: httpx.Response) -> dict[str, Any]:
        try:
            value = response.json()
        except ValueError as exc:
            raise ContractValidationError(
                "Server response is not valid JSON",
                code="INVALID_JSON_RESPONSE",
            ) from exc
        if not isinstance(value, dict):
            raise ContractValidationError(
                "Server response must be a JSON object",
                code="INVALID_RESPONSE_SHAPE",
            )
        return value

    @classmethod
    def _parse_model(cls, response: httpx.Response, model: type[_ModelT]) -> _ModelT:
        try:
            return model.model_validate(cls._json_object(response))
        except ValidationError as exc:
            raise ContractValidationError(
                f"Server response does not match {model.__name__}: {exc}",
                code="CONTRACT_VALIDATION_ERROR",
            ) from exc
