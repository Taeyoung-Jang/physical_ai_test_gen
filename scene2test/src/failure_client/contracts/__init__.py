"""Public Server integration contract surface."""

from .artifacts import ArtifactRef, LocalArtifact
from .base import ContractModel, VersionedContractModel, canonical_json, canonical_sha256
from .capabilities import CapabilitySnapshot
from .errors import (
    ArtifactIntegrityError,
    ContractValidationError,
    ErrorEnvelope,
    ErrorInfo,
    GatewayError,
    GatewayHTTPError,
)
from .interventions import InterventionSpec
from .registry import RegistryEntry, RegistrySnapshot
from .resources import ResourceRef, ResourceSelection, RobotRef, SceneSnapshot
from .rollouts import (
    CancelResult,
    ExecutionSpec,
    ExecutionSummary,
    RecordingSpec,
    RemoteJobState,
    ResearchContext,
    RolloutAccepted,
    RolloutJobStatus,
    RolloutRequest,
    RolloutResult,
    TaskSpec,
)
from .scene_queries import SceneQueryRequest, SceneQueryResult

__all__ = [
    "ArtifactIntegrityError",
    "ArtifactRef",
    "CancelResult",
    "CapabilitySnapshot",
    "ContractModel",
    "ContractValidationError",
    "ErrorEnvelope",
    "ErrorInfo",
    "ExecutionSummary",
    "ExecutionSpec",
    "GatewayError",
    "GatewayHTTPError",
    "InterventionSpec",
    "LocalArtifact",
    "RecordingSpec",
    "RegistryEntry",
    "RegistrySnapshot",
    "RemoteJobState",
    "ResearchContext",
    "ResourceRef",
    "ResourceSelection",
    "RobotRef",
    "RolloutAccepted",
    "RolloutJobStatus",
    "RolloutRequest",
    "RolloutResult",
    "SceneQueryRequest",
    "SceneQueryResult",
    "SceneSnapshot",
    "TaskSpec",
    "VersionedContractModel",
    "canonical_json",
    "canonical_sha256",
]
