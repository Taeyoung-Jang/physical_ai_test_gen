"""Public Server integration contract surface."""

from .artifacts import ArtifactRef, LocalArtifact
from .base import ContractModel, VersionedContractModel, canonical_json, canonical_sha256
from .capabilities import (
    ArtifactFormatCapability,
    CapabilityLimits,
    CapabilitySnapshot,
    OperationCapability,
    QueryCapability,
    RecordingChannelCapability,
)
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
    StandardEvent,
    TaskSpec,
)
from .scene_queries import SceneQueryRequest, SceneQueryResult

__all__ = [
    "ArtifactIntegrityError",
    "ArtifactFormatCapability",
    "ArtifactRef",
    "CancelResult",
    "CapabilitySnapshot",
    "CapabilityLimits",
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
    "OperationCapability",
    "QueryCapability",
    "RecordingSpec",
    "RecordingChannelCapability",
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
    "StandardEvent",
    "SceneQueryRequest",
    "SceneQueryResult",
    "SceneSnapshot",
    "TaskSpec",
    "VersionedContractModel",
    "canonical_json",
    "canonical_sha256",
]
