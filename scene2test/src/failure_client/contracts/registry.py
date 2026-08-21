"""Remote registry snapshot contracts."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .base import ContractModel, VersionedContractModel


class RegistryEntry(ContractModel):
    id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    status: str | None = None
    compatibility_summary: dict[str, Any] = Field(default_factory=dict)


class RegistrySnapshot(VersionedContractModel):
    registry_revision: str = Field(min_length=1)
    scenes: list[RegistryEntry] = Field(default_factory=list)
    robots: list[RegistryEntry] = Field(default_factory=list)
    controllers: list[RegistryEntry] = Field(default_factory=list)
    policies: list[RegistryEntry] = Field(default_factory=list)
    tasks: list[RegistryEntry] = Field(default_factory=list)

