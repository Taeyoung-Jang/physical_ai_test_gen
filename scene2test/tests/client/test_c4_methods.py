from __future__ import annotations

from failure_client.contracts import CapabilitySnapshot, SceneSnapshot
from failure_client.methods import (
    CandidateObservation,
    MethodContext,
    MethodRegistry,
    RandomMethod,
    SobolMethod,
    derive_repeat_seed,
)
from failure_client.world_model import WorldModelProjector

from .test_c1_durable_rollout import make_protocol, make_repository


def make_context(load_contract_fixture) -> MethodContext:
    protocol = make_protocol()
    capabilities = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    scene = SceneSnapshot.model_validate(load_contract_fixture("scene_snapshot_v1.json"))
    world = WorldModelProjector().project(
        task=protocol.task,
        resources=protocol.resources,
        scene=scene,
        capabilities=capabilities,
    )
    return MethodContext(
        experiment_id="exp_001",
        method_instance_id="method_001",
        master_seed=101,
        world_model=world,
        capabilities=capabilities,
    )


def parametric_config(maximum_candidates: int = 10) -> dict:
    return {
        "operation": "add_primitive",
        "parameter_space": {
            "obstacle_x": {"kind": "continuous", "low": 0.8, "high": 2.5},
            "obstacle_y": {"kind": "continuous", "low": -0.8, "high": 0.8},
            "shape": {"kind": "categorical", "choices": ["box", "cylinder"]},
        },
        "static_parameters": {
            "shape": "box",
            "position_m": [0.0, 0.0, 0.2],
            "size_m": [0.4, 0.2, 0.4],
        },
        "parameter_bindings": {
            "obstacle_x": "position_m.0",
            "obstacle_y": "position_m.1",
            "shape": "shape",
        },
        "maximum_candidates": maximum_candidates,
    }


def test_random_method_checkpoint_restores_exact_next_candidates(load_contract_fixture):
    context = make_context(load_contract_fixture)
    method = RandomMethod(parametric_config())
    method.initialize(context)
    method.propose(3)
    state = method.state_dict()
    expected = method.propose(2)

    restored = RandomMethod(parametric_config())
    restored.initialize(context)
    restored.load_state_dict(state)
    actual = restored.propose(2)

    assert actual == expected
    restored.observe(
        [
            CandidateObservation(
                candidate_id=actual[0].candidate_id,
                status="EVALUATED",
                failure=True,
            )
        ]
    )
    assert restored.state_dict()["failure_count"] == 1


def test_sobol_method_checkpoint_restores_exact_next_candidates(load_contract_fixture):
    context = make_context(load_contract_fixture)
    method = SobolMethod(parametric_config())
    method.initialize(context)
    method.propose(3)
    state = method.state_dict()
    expected = method.propose(3)

    restored = SobolMethod(parametric_config())
    restored.initialize(context)
    restored.load_state_dict(state)
    actual = restored.propose(3)

    assert actual == expected


def test_method_registry_exposes_only_explicit_builtins():
    registry = MethodRegistry.with_builtins()

    assert registry.list_plugin_ids() == [
        "legacy_afs_import",
        "legacy_lam_guided_import",
        "manual",
        "random_parametric",
        "sobol_parametric",
    ]
    assert isinstance(registry.create("random_parametric", parametric_config()), RandomMethod)


def test_legacy_adapters_translate_exported_records_without_running_pybullet(
    load_contract_fixture,
):
    context = make_context(load_contract_fixture)
    registry = MethodRegistry.with_builtins()
    afs = registry.create(
        "legacy_afs_import",
        {
            "operation": "add_primitive",
            "records": [{"mutation_params": {"obstacle_x": 1.2}}],
            "static_parameters": {"shape": "box", "position": {}},
            "parameter_bindings": {"obstacle_x": "position.x"},
        },
    )
    afs.initialize(context)
    afs_proposal = afs.propose(1)[0]
    lam = registry.create(
        "legacy_lam_guided_import",
        {
            "operation": "add_primitive",
            "cases": [
                {
                    "family": "path_blocker",
                    "expected_failure": "collision_or_clearance_failure",
                    "insert_specs": [
                        {
                            "asset_id": "procedural_box",
                            "obj_id": "blocker_1",
                            "position": [1.0, 0.0, 0.2],
                        }
                    ],
                }
            ],
        },
    )
    lam.initialize(context)
    lam_proposal = lam.propose(1)[0]

    assert afs_proposal.intervention_intent["parameters"]["position"]["x"] == 1.2
    assert lam_proposal.intervention_intent["operations"][0]["parameters"] == {
        "asset_id": "procedural_box",
        "object_id": "blocker_1",
        "position_m": [1.0, 0.0, 0.2],
    }
    assert lam_proposal.hypothesis.mechanism == "collision_or_clearance_failure"


def test_method_checkpoint_round_trips_through_sqlite(tmp_path, load_contract_fixture):
    capabilities = CapabilitySnapshot.model_validate(
        load_contract_fixture("capabilities_v1.json")
    )
    repository = make_repository(tmp_path, capabilities)
    method = RandomMethod(parametric_config())
    method.initialize(make_context(load_contract_fixture))
    method.propose(4)

    sequence = repository.save_method_checkpoint("exp_001", "method_001", method.state_dict())
    loaded = repository.load_latest_method_checkpoint("exp_001", "method_001")

    assert sequence == 0
    assert loaded == method.state_dict()


def test_repeat_seed_is_stable_and_separates_repeats():
    first = derive_repeat_seed(101, "sha256:candidate", 0)
    same = derive_repeat_seed(101, "sha256:candidate", 0)
    next_repeat = derive_repeat_seed(101, "sha256:candidate", 1)

    assert first == same
    assert first != next_repeat
    assert 0 <= first < 2**32
