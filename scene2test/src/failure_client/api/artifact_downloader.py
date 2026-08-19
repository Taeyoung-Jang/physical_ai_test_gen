"""Atomic, content-verified artifact persistence."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

from failure_client.contracts import ArtifactIntegrityError, ArtifactRef, LocalArtifact

_SAFE_SUFFIX_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def persist_verified_artifact(
    ref: ArtifactRef,
    payload: bytes,
    artifact_dir: Path,
) -> LocalArtifact:
    """Verify bytes, then atomically place them at a content-addressed path."""

    actual_size = len(payload)
    if actual_size != ref.size_bytes:
        raise ArtifactIntegrityError(
            f"artifact {ref.artifact_id} size mismatch: "
            f"expected {ref.size_bytes}, got {actual_size}",
            code="ARTIFACT_SIZE_MISMATCH",
            retryable=True,
        )

    actual_hash = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    if actual_hash != ref.sha256:
        raise ArtifactIntegrityError(
            f"artifact {ref.artifact_id} checksum mismatch",
            code="ARTIFACT_CHECKSUM_MISMATCH",
            retryable=True,
        )

    artifact_dir.mkdir(parents=True, exist_ok=True)
    digest = ref.sha256.removeprefix("sha256:")
    suffix = ref.format.lower() if _SAFE_SUFFIX_RE.fullmatch(ref.format) else "bin"
    final_path = artifact_dir / f"{digest}.{suffix}"

    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=artifact_dir, prefix=".download-", delete=False) as f:
            temp_path = Path(f.name)
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, final_path)
        temp_path = None
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)

    return LocalArtifact(
        artifact_id=ref.artifact_id,
        path=final_path,
        size_bytes=actual_size,
        sha256=actual_hash,
    )

