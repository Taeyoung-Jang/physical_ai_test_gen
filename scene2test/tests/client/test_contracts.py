from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from failure_client.contracts import (
    ArtifactRef,
    CapabilitySnapshot,
    ExecutionSpec,
    RecordingSpec,
    ResearchContext,
    ResourceRef,
    ResourceSelection,
    RobotRef,
    RolloutRequest,
    TaskSpec,
    canonical_json,
    canonical_sha256,
)


def make_rollout_request(parameters: dict | None = None) -> RolloutRequest:
    return RolloutRequest(
        client_request_id="req_001",
        research_context=ResearchContext(
            experiment_id="exp_001",
            candidate_id="cand_001",
            method_instance_id="sobol_001",
        ),
        resources=ResourceSelection(
            scene=ResourceRef(id="scene_001", revision="sha256:scene-v1"),
            robot=RobotRef(
                id="unitree_g1",
                profile_id="default",
                revision="sha256:robot-v1",
            ),
            controller=ResourceRef(
                id="groot_locomotion",
                revision="sha256:controller-v1",
            ),
            policy=ResourceRef(
                id="scripted_navigation",
                revision="sha256:policy-v1",
            ),
        ),
        task=TaskSpec(
            schema="navigate_to_pose@1.0",
            parameters=parameters or {"target_position_m": [3.0, 0.0, 0.0]},
        ),
        execution=ExecutionSpec(seed=42, maximum_duration_s=20.0),
        recording=RecordingSpec(video="always"),
    )


def test_capability_fixture_is_typed_and_forward_compatible(load_contract_fixture):
    payload = load_contract_fixture("capabilities_v1.json")
    payload["future_optional_field"] = {"enabled": True}

    capability = CapabilitySnapshot.model_validate(payload)

    assert capability.intervention_operations[0].operation_id == "add_primitive"
    assert capability.recording_channels[0].fields[-1] == "joint_positions"
    assert capability.model_extra == {"future_optional_field": {"enabled": True}}


def test_revision_is_required():
    with pytest.raises(ValidationError):
        ResourceRef.model_validate({"id": "scene_001"})


def test_unsupported_contract_major_version_fails_fast(load_contract_fixture):
    payload = load_contract_fixture("capabilities_v1.json")
    payload["schema_version"] = "2.0"

    with pytest.raises(ValidationError, match="unsupported contract major"):
        CapabilitySnapshot.model_validate(payload)


def test_canonical_request_hash_ignores_mapping_insertion_order():
    first = make_rollout_request({"z": 1, "a": {"y": 2, "x": 3}})
    second = make_rollout_request({"a": {"x": 3, "y": 2}, "z": 1})

    assert canonical_json(first) == canonical_json(second)
    assert canonical_sha256(first) == canonical_sha256(second)
    assert b'"schema":"navigate_to_pose@1.0"' in canonical_json(first)


def test_artifact_hash_is_normalized():
    payload = b"trajectory"
    digest = hashlib.sha256(payload).hexdigest().upper()

    ref = ArtifactRef(
        artifact_id="artifact_001",
        kind="state_trajectory",
        format="parquet",
        size_bytes=len(payload),
        sha256=digest,
    )

    assert ref.sha256 == f"sha256:{digest.lower()}"


def test_artifact_rejects_malformed_hash():
    with pytest.raises(ValidationError):
        ArtifactRef(
            artifact_id="artifact_001",
            kind="state_trajectory",
            format="parquet",
            size_bytes=1,
            sha256="not-a-hash",
        )
