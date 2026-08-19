"""Remote and locally verified artifact contracts."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import Field, field_validator

from .base import ContractModel

_SHA256_RE = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")


def normalize_sha256(value: str) -> str:
    match = _SHA256_RE.fullmatch(value)
    if not match:
        raise ValueError("sha256 must contain exactly 64 hexadecimal characters")
    return f"sha256:{match.group(1).lower()}"


class ArtifactRef(ContractModel):
    artifact_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    format: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    sha256: str
    download_url: str | None = None

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return normalize_sha256(value)


class LocalArtifact(ContractModel):
    artifact_id: str = Field(min_length=1)
    path: Path
    size_bytes: int = Field(ge=0)
    sha256: str

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        return normalize_sha256(value)

