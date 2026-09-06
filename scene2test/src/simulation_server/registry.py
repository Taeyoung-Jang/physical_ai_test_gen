from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from failure_client.contracts import RegistryEntry, RegistrySnapshot, SceneSnapshot

RESOURCE_TYPES = ("scenes", "robots", "controllers", "policies", "tasks")


class RegistryError(LookupError):
    pass


@dataclass(slots=True)
class ManifestRegistry:
    root: Path

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def snapshot(self) -> RegistrySnapshot:
        groups = {kind: self._entries(kind) for kind in RESOURCE_TYPES}
        canonical = json.dumps(
            {
                kind: [entry.model_dump(mode="json") for entry in groups[kind]]
                for kind in RESOURCE_TYPES
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return RegistrySnapshot(
            registry_revision=f"sha256:{hashlib.sha256(canonical).hexdigest()}", **groups
        )

    def resolve(self, kind: str, resource_id: str, revision: str) -> dict[str, Any]:
        if kind not in RESOURCE_TYPES:
            raise RegistryError(f"unknown resource type: {kind}")
        for manifest in self._manifests(kind):
            if manifest["id"] == resource_id and manifest["revision"] == revision:
                return manifest
        raise RegistryError(f"{kind[:-1]} {resource_id}@{revision} was not found")

    def scene_snapshot(self, scene_id: str, revision: str) -> SceneSnapshot:
        manifest = self.resolve("scenes", scene_id, revision)
        return SceneSnapshot(
            scene_id=scene_id, scene_revision=revision, **manifest.get("snapshot", {})
        )

    def _entries(self, kind: str) -> list[RegistryEntry]:
        return [
            RegistryEntry(
                id=item["id"],
                revision=item["revision"],
                status=item.get("status", "READY"),
                compatibility_summary=item.get("compatibility", {}),
            )
            for item in self._manifests(kind)
        ]

    def _manifests(self, kind: str) -> list[dict[str, Any]]:
        directory = self.root / kind
        if not directory.exists():
            return []
        result: list[dict[str, Any]] = []
        for path in sorted(directory.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or not value.get("id") or not value.get("revision"):
                raise ValueError(f"invalid registry manifest: {path}")
            result.append(value)
        return result
