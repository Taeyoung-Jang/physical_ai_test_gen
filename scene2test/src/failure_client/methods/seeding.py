"""Versioned deterministic seed derivation for candidate repeats."""

from __future__ import annotations

import hashlib


def derive_repeat_seed(
    master_seed: int,
    candidate_sha256: str,
    repeat_index: int,
    *,
    version: str = "sha256-v1",
) -> int:
    if version != "sha256-v1":
        raise ValueError(f"unsupported seed derivation version: {version}")
    if repeat_index < 0:
        raise ValueError("repeat_index must be non-negative")
    material = f"{version}\0{master_seed}\0{candidate_sha256}\0{repeat_index}".encode()
    return int.from_bytes(hashlib.sha256(material).digest()[:4], "big", signed=False)

