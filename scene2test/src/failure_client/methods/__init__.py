"""Replaceable failure-discovery method framework."""

from .adapters import LegacyAFSImportMethod, LegacyLAMGuidedImportMethod
from .base import (
    CandidateObservation,
    FailureDiscoveryMethod,
    MethodContext,
    MethodNotInitializedError,
    StopDecision,
)
from .baselines import ManualMethod, RandomMethod, SobolMethod
from .parameters import ParameterSpec, ParametricMethodConfig
from .registry import MethodRegistry
from .seeding import derive_repeat_seed

__all__ = [
    "CandidateObservation",
    "FailureDiscoveryMethod",
    "LegacyAFSImportMethod",
    "LegacyLAMGuidedImportMethod",
    "ManualMethod",
    "MethodContext",
    "MethodNotInitializedError",
    "MethodRegistry",
    "ParameterSpec",
    "ParametricMethodConfig",
    "RandomMethod",
    "SobolMethod",
    "StopDecision",
    "derive_repeat_seed",
]
