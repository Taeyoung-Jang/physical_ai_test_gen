"""Normalized Server error envelope and gateway exceptions."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, VersionedContractModel


class ErrorInfo(ContractModel):
    code: str = Field(min_length=1)
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None


class ErrorEnvelope(VersionedContractModel):
    error: ErrorInfo


class GatewayError(RuntimeError):
    """Base normalized external Server failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "GATEWAY_ERROR",
        retryable: bool = False,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.request_id = request_id


class GatewayHTTPError(GatewayError):
    def __init__(self, status_code: int, info: ErrorInfo) -> None:
        super().__init__(
            info.message,
            code=info.code,
            retryable=info.retryable,
            request_id=info.request_id,
        )
        self.status_code = status_code
        self.details = info.details


class ContractValidationError(GatewayError):
    pass


class ArtifactIntegrityError(GatewayError):
    pass

