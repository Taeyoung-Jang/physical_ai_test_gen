"""Fail-fast compatibility checks between methods and Server capabilities."""

from __future__ import annotations

from pydantic import Field

from failure_client.contracts import CapabilitySnapshot, ContractModel


class VersionedRequirement(ContractModel):
    capability_id: str = Field(min_length=1)
    version: str = "1.x"
    required_fields: list[str] = Field(default_factory=list)
    required_features: dict[str, object] = Field(default_factory=dict)


class MethodRequirements(ContractModel):
    contract_version: str = "1.x"
    scene_queries: list[VersionedRequirement] = Field(default_factory=list)
    intervention_operations: list[VersionedRequirement] = Field(default_factory=list)
    recording_channels: list[VersionedRequirement] = Field(default_factory=list)


class CapabilityIssue(ContractModel):
    code: str
    message: str
    capability_id: str | None = None


class CompatibilityResult(ContractModel):
    compatible: bool
    issues: list[CapabilityIssue] = Field(default_factory=list)


def check_method_compatibility(
    requirements: MethodRequirements,
    available: CapabilitySnapshot,
) -> CompatibilityResult:
    issues: list[CapabilityIssue] = []
    if not any(
        _version_matches(requirements.contract_version, version)
        for version in available.contract_versions
    ):
        issues.append(
            CapabilityIssue(
                code="CONTRACT_VERSION_MISMATCH",
                message=(
                    f"requires {requirements.contract_version}; "
                    f"available={available.contract_versions}"
                ),
            )
        )

    query_map = {item.query_id: item for item in available.scene_queries}
    operation_map = {item.operation_id: item for item in available.intervention_operations}
    channel_map = {item.channel_id: item for item in available.recording_channels}

    for required in requirements.scene_queries:
        item = query_map.get(required.capability_id)
        _check_version(required, item.version if item else None, issues, "SCENE_QUERY")
    for required in requirements.intervention_operations:
        item = operation_map.get(required.capability_id)
        _check_version(required, item.version if item else None, issues, "INTERVENTION")
        if item is not None:
            _check_features(required, item.features, issues)
    for required in requirements.recording_channels:
        item = channel_map.get(required.capability_id)
        _check_version(required, item.version if item else None, issues, "RECORDING_CHANNEL")
        if item is not None:
            missing_fields = sorted(set(required.required_fields) - set(item.fields))
            if missing_fields:
                issues.append(
                    CapabilityIssue(
                        code="RECORDING_FIELDS_MISSING",
                        capability_id=required.capability_id,
                        message=f"missing fields: {missing_fields}",
                    )
                )
    return CompatibilityResult(compatible=not issues, issues=issues)


def _check_version(
    required: VersionedRequirement,
    available_version: str | None,
    issues: list[CapabilityIssue],
    prefix: str,
) -> None:
    if available_version is None:
        issues.append(
            CapabilityIssue(
                code=f"{prefix}_MISSING",
                capability_id=required.capability_id,
                message="capability is unavailable",
            )
        )
    elif not _version_matches(required.version, available_version):
        issues.append(
            CapabilityIssue(
                code=f"{prefix}_VERSION_MISMATCH",
                capability_id=required.capability_id,
                message=f"requires {required.version}; available={available_version}",
            )
        )


def _check_features(
    required: VersionedRequirement,
    available_features: dict[str, object],
    issues: list[CapabilityIssue],
) -> None:
    for name, value in required.required_features.items():
        available = available_features.get(name)
        if isinstance(available, list):
            matched = value in available
        else:
            matched = available == value
        if not matched:
            issues.append(
                CapabilityIssue(
                    code="INTERVENTION_FEATURE_MISSING",
                    capability_id=required.capability_id,
                    message=f"requires feature {name}={value!r}; available={available!r}",
                )
            )


def _version_matches(requirement: str, available: str) -> bool:
    requirement = requirement.strip()
    available = available.strip()
    if requirement.endswith(".x"):
        return available.split(".", 1)[0] == requirement.split(".", 1)[0]
    if requirement.startswith(">="):
        lower = requirement.removeprefix(">=").split(",", 1)[0]
        return tuple(map(int, available.split("."))) >= tuple(map(int, lower.split(".")))
    return requirement == available

