"""Base types and canonical serialization for the Server integration contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Immutable DTO that tolerates additive fields within a contract major version."""

    model_config = ConfigDict(extra="allow", frozen=True, populate_by_name=True)


class VersionedContractModel(ContractModel):
    """Top-level contract envelope."""

    schema_version: str = Field(default="1.0", pattern=r"^\d+\.\d+$")


def canonical_json(value: BaseModel | Mapping[str, Any]) -> bytes:
    """Return deterministic UTF-8 JSON used for request hashing and idempotency."""

    if isinstance(value, BaseModel):
        data = value.model_dump(mode="json", by_alias=True, exclude_none=True)
    else:
        data = dict(value)
    return json.dumps(
        data,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_sha256(value: BaseModel | Mapping[str, Any]) -> str:
    """Return a prefixed SHA-256 digest of the canonical JSON representation."""

    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"

