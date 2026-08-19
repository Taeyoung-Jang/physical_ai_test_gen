"""Content-addressed immutable experiment protocol locks."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from failure_client.contracts import (
    CapabilitySnapshot,
    VersionedContractModel,
    canonical_sha256,
)

from .protocol import ExperimentProtocol


class ProtocolLock(VersionedContractModel):
    created_at: datetime
    protocol: dict[str, Any]
    protocol_sha256: str
    capability_snapshot: dict[str, Any]
    capability_sha256: str
    registry_revision: str
    client_commit: str | None = None
    dependency_lock_sha256: str | None = None
    seed_derivation_version: str = "sha256-v1"
    lock_sha256: str = Field(min_length=1)


def build_protocol_lock(
    protocol: ExperimentProtocol,
    capabilities: CapabilitySnapshot,
    *,
    repository_dir: Path | None = None,
    dependency_lock_path: Path | None = None,
) -> ProtocolLock:
    protocol_data = protocol.model_dump(mode="json", by_alias=True, exclude_none=True)
    capability_data = capabilities.model_dump(mode="json", by_alias=True, exclude_none=True)
    core = {
        "schema_version": "1.0",
        "protocol": protocol_data,
        "protocol_sha256": canonical_sha256(protocol),
        "capability_snapshot": capability_data,
        "capability_sha256": canonical_sha256(capabilities),
        "registry_revision": capabilities.registry_revision,
        "client_commit": _git_commit(repository_dir),
        "dependency_lock_sha256": _file_sha256(dependency_lock_path),
        "seed_derivation_version": protocol.execution.seed_policy,
    }
    return ProtocolLock(
        **core,
        created_at=datetime.now(UTC),
        lock_sha256=canonical_sha256(core),
    )


def write_protocol_lock(path: Path, lock: ProtocolLock) -> ProtocolLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing_data = yaml.safe_load(path.read_text(encoding="utf-8"))
        existing = ProtocolLock.model_validate(existing_data)
        if existing.lock_sha256 != lock.lock_sha256:
            raise ValueError(
                f"immutable protocol lock already exists with different content: {path}"
            )
        return existing
    data = lock.model_dump(mode="json", by_alias=True, exclude_none=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=True),
        encoding="utf-8",
    )
    return lock


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _git_commit(repository_dir: Path | None) -> str | None:
    if repository_dir is None:
        return None
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository_dir,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or None if result.returncode == 0 else None
