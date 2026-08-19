from __future__ import annotations

from failure_client.api import FakeSimulationGateway
from failure_client.candidates import (
    CandidateProposal,
    CandidateValidator,
    InterventionBuilder,
)
from failure_client.contracts import (
    CapabilitySnapshot,
    RegistryEntry,
    RegistrySnapshot,
    ResourceRef,
    SceneQueryRequest,
    SceneQueryResult,
    SceneSnapshot,
)
from failure_client.registry import (
    MethodRequirements,
    RegistrySynchronizer,
    VersionedRequirement,
    check_method_compatibility,
)
from failure_client.storage import ClientRepository
from failure_client.world_model import WorldModelProjector

from .test_c1_durable_rollout import make_protocol


def make_gateway(tmp_path, load_contract_fixture) -> FakeSimulationGateway:
    capability = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    registry = RegistrySnapshot.model_validate(load_contract_fixture("registry_v1.json"))
    scene = SceneSnapshot.model_validate(load_contract_fixture("scene_snapshot_v1.json"))
    return FakeSimulationGateway(
        capabilities=capability,
        registry=registry,
        artifact_dir=tmp_path / "artifacts",
        scene_snapshots={(scene.scene_id, scene.scene_revision): scene},
    )


def test_registry_sync_preserves_pinned_revision_and_moves_latest(
    tmp_path,
    load_contract_fixture,
):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    repository = ClientRepository(tmp_path / "client.sqlite")
    synchronizer = RegistrySynchronizer(repository, gateway)
    first = synchronizer.sync()
    assert first.scene_count == 1

    old_entry = repository.get_registry_entry("scene", "scene_001")
    new_entry = RegistryEntry(id="scene_001", revision="sha256:scene-v2", status="READY")
    gateway.registry = gateway.registry.model_copy(
        update={"registry_revision": "sha256:registry-v2", "scenes": [new_entry]}
    )
    gateway.capabilities = gateway.capabilities.model_copy(
        update={"registry_revision": "sha256:registry-v2"}
    )
    synchronizer.sync()

    assert repository.get_registry_entry("scene", "scene_001").revision == "sha256:scene-v2"
    pinned = repository.get_registry_entry(
        "scene",
        "scene_001",
        revision="sha256:scene-v1",
    )
    assert pinned == old_entry


def test_scene_snapshot_and_query_are_cached_by_revision(tmp_path, load_contract_fixture):
    gateway = make_gateway(tmp_path, load_contract_fixture)
    repository = ClientRepository(tmp_path / "client.sqlite")
    synchronizer = RegistrySynchronizer(repository, gateway)
    ref = ResourceRef(id="scene_001", revision="sha256:scene-v1")

    first = synchronizer.require_scene_snapshot(ref)
    gateway.scene_snapshots.clear()
    assert synchronizer.require_scene_snapshot(ref) == first

    request = SceneQueryRequest(
        scene=ref,
        query_id="get_clearance",
        query_version="1.0",
        parameters={"from": [0, 0, 0], "to": [1, 0, 0]},
    )
    result = SceneQueryResult(
        scene=ref,
        query_id="get_clearance",
        query_implementation_version="1.0",
        result={"clearance_m": 0.44},
    )
    gateway.query_results[(ref.id, ref.revision, request.query_id)] = result
    assert synchronizer.query_scene(request) == result
    gateway.query_results.clear()
    assert synchronizer.query_scene(request) == result


def test_world_model_projects_only_task_relevant_objects(load_contract_fixture):
    protocol = make_protocol()
    scene_payload = load_contract_fixture("scene_snapshot_v1.json")
    scene_payload["objects"] = [
        {"id": "target_01", "category": "box", "aabb": {}},
        {"id": "chair_01", "category": "chair", "aabb": {}},
    ]
    scene = SceneSnapshot.model_validate(scene_payload)
    task = protocol.task.model_copy(
        update={"parameters": {"target_object_id": "target_01"}}
    )
    capabilities = CapabilitySnapshot.model_validate(load_contract_fixture("capabilities_v1.json"))

    world = WorldModelProjector().project(
        task=task,
        resources=protocol.resources,
        scene=scene,
        capabilities=capabilities,
    )

    assert [item["id"] for item in world.relevant_objects] == ["target_01"]
    assert world.scene_revision == "sha256:scene-v1"
    assert world.robot_profile["id"] == "unitree_g1"


def test_method_capability_matching_reports_missing_fields(load_contract_fixture):
    capabilities = CapabilitySnapshot.model_validate(load_contract_fixture("capabilities_v1.json"))
    requirements = MethodRequirements(
        contract_version="1.x",
        intervention_operations=[
            VersionedRequirement(
                capability_id="add_primitive",
                version="1.x",
                required_features={"shapes": "box"},
            )
        ],
        recording_channels=[
            VersionedRequirement(
                capability_id="state_trajectory",
                version="1.x",
                required_fields=["base_pose", "joint_torques"],
            )
        ],
    )

    result = check_method_compatibility(requirements, capabilities)

    assert result.compatible is False
    assert [issue.code for issue in result.issues] == ["RECORDING_FIELDS_MISSING"]


def test_candidate_build_is_canonical_and_capability_validated(load_contract_fixture):
    capabilities = CapabilitySnapshot.model_validate(load_contract_fixture("capabilities_v1.json"))
    first = CandidateProposal(
        candidate_id="cand_001",
        method_instance_id="random_001",
        hypothesis={"mechanism": "Obstacle may block the path."},
        intervention_intent={
            "operation": "add_primitive",
            "parameters": {
                "shape": "box",
                "size_m": [0.5, 0.2, 0.4],
                "position_m": [1.5, 0.0, 0.2],
            },
        },
    )
    second = first.model_copy(
        update={
            "candidate_id": "cand_other",
            "hypothesis": {"mechanism": "A different explanation."},
        }
    )
    builder = InterventionBuilder()
    built = builder.build(first)

    assert builder.build(second).canonical_sha256 == built.canonical_sha256
    assert built.interventions[0].kind == "scene.add_primitive"
    assert CandidateValidator().validate(built, capabilities).valid is True


def test_candidate_validator_rejects_dependency_cycle(load_contract_fixture):
    capabilities = CapabilitySnapshot.model_validate(load_contract_fixture("capabilities_v1.json"))
    proposal = CandidateProposal(
        candidate_id="cand_cycle",
        method_instance_id="manual_001",
        intervention_intent={
            "operations": [
                {
                    "operation": "add_primitive",
                    "operation_id": "op_a",
                    "depends_on": ["op_b"],
                },
                {
                    "operation": "add_primitive",
                    "operation_id": "op_b",
                    "depends_on": ["op_a"],
                },
            ]
        },
    )

    result = CandidateValidator().validate(InterventionBuilder().build(proposal), capabilities)

    assert result.valid is False
    assert "CYCLIC_OPERATION_DEPENDENCY" in {issue.code for issue in result.issues}
