"""Explicit built-in method registry; external entry points are deferred."""

from __future__ import annotations

from collections.abc import Callable
from importlib import metadata
from typing import Any

from .adapters import LegacyAFSImportMethod, LegacyLAMGuidedImportMethod
from .base import FailureDiscoveryMethod
from .baselines import ManualMethod, RandomMethod, SobolMethod

MethodFactory = Callable[[dict[str, Any]], FailureDiscoveryMethod]


class MethodRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, MethodFactory] = {}

    @classmethod
    def with_builtins(cls, *, load_external: bool = False) -> MethodRegistry:
        registry = cls()
        registry.register(RandomMethod.plugin_id, RandomMethod)
        registry.register(SobolMethod.plugin_id, SobolMethod)
        registry.register(ManualMethod.plugin_id, ManualMethod)
        registry.register(LegacyAFSImportMethod.plugin_id, LegacyAFSImportMethod)
        registry.register(
            LegacyLAMGuidedImportMethod.plugin_id,
            LegacyLAMGuidedImportMethod,
        )
        if load_external:
            registry.load_entry_points()
        return registry

    def register(self, plugin_id: str, factory: MethodFactory) -> None:
        if plugin_id in self._factories:
            raise ValueError(f"method plugin already registered: {plugin_id}")
        self._factories[plugin_id] = factory

    def create(self, plugin_id: str, config: dict[str, Any]) -> FailureDiscoveryMethod:
        try:
            factory = self._factories[plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown method plugin: {plugin_id}") from exc
        method = factory(config)
        if not isinstance(method, FailureDiscoveryMethod):
            raise TypeError(f"method plugin does not implement FailureDiscoveryMethod: {plugin_id}")
        return method

    def load_entry_points(self) -> None:
        entries = metadata.entry_points(group="failure_client.methods")
        for entry in sorted(entries, key=lambda item: item.name):
            if entry.name in self._factories:
                raise ValueError(f"external method shadows registered plugin: {entry.name}")
            loaded = entry.load()
            if not callable(loaded):
                raise TypeError(f"method entry point is not callable: {entry.name}")
            self.register(entry.name, loaded)

    def list_plugin_ids(self) -> list[str]:
        return sorted(self._factories)
