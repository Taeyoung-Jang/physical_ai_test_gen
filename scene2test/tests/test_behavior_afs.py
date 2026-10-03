import copy
import hashlib
import json

import pytest

from clear_path.contracts import Fixture
from clear_path.fixture import identity, world_xml
from llm_afs import behavior as b
from robot_vlm.scene_config import validate_scene


def observation(**changes):
    return {
        "run": "example",
        "parameters": {"box_mass_kg": 2.0, "box_friction": 0.5, "floor_friction": 0.8},
        "condition_sha256": "same",
        "condition": {},
        "valid_execution": True,
        "evaluation_profile": "goal_outcome_v1",
        "task_outcome": "FAIL",
        "task_success": False,
        "reason": "BUDGET_EXHAUSTED",
        "evidence": [{"id": "outcome"}],
        **changes,
    }


def proposal(ctx):
    return b.Proposal(
        context_sha256=b.digest(ctx),
        spaces=[
            b.Space(
                mode=mode,
                axis=axis,
                low=lo,
                high=hi,
                evidence_refs=["outcome"],
                hypothesis="test",
                alternative="controller",
                falsification="outcome",
            )
            for mode, axis, lo, hi in [
                ("boundary_probe", "box_mass_kg", 1.0, 3.0),
                ("cross_mechanism", "floor_friction", 0.3, 1.0),
            ]
        ],
    )


def test_paired_probes_and_independent_exploration(tmp_path):
    ctx = b.context(observation())
    suite = b.compile_suite(ctx, proposal(ctx), tmp_path)
    assert suite["ready"] == 8
    for row in suite["candidates"]:
        validate_scene(b.read(row["config"]))
        if row["axis"]:
            changed = [k for k in b.AXES if row["parameters"][k] != ctx["latest"]["parameters"][k]]
            assert changed == [row["axis"]]
    assert suite["brackets"] == []
    assert len([r for r in suite["candidates"] if r["strategy"] == "independent_exploration"]) == 2


@pytest.mark.parametrize("change", ["outside", "empty", "no_evidence", "stale"])
def test_bad_proposals_rejected(change):
    ctx = b.context(observation())
    p = proposal(ctx)
    if change == "outside":
        p.spaces[0].low = -1.0
    elif change == "empty":
        p.spaces[0].high = p.spaces[0].low
    elif change == "no_evidence":
        p.spaces[0].evidence_refs = ["invented"]
    else:
        p.context_sha256 = "old"
    with pytest.raises(ValueError):
        b.validate(p, ctx)


def test_bracket_requires_opposite_comparable_task_outcomes(tmp_path):
    a = observation()
    other = copy.deepcopy(a)
    other["run"] = "other"
    other["parameters"]["box_mass_kg"] = 1.0
    assert not b.brackets(a, [other])
    other["task_success"] = True
    other["task_outcome"] = "PASS"
    assert b.brackets(a, [other])[0]["midpoint"] == 1.5
    ctx = b.context(a, [other])
    suite = b.compile_suite(ctx, proposal(ctx), tmp_path)
    rows = [r for r in suite["candidates"] if r["strategy"] == "boundary_probe"]
    assert len(rows) == 1 and rows[0]["parameters"]["box_mass_kg"] == 1.5
    other["condition_sha256"] = "different_robot"
    assert not b.brackets(a, [other])
    other["condition_sha256"] = "same"
    other["parameters"]["floor_friction"] = 0.7
    assert not b.brackets(a, [other])
    other["parameters"]["floor_friction"] = 0.8
    other["returned_models"] = ["different-returned-model"]
    assert not b.brackets(a, [other])


def test_dedup_keeps_explicit_repeats_not_axis_cooldown(tmp_path):
    ctx = b.context(observation())
    first = b.compile_suite(ctx, proposal(ctx), tmp_path / "first")
    second = b.compile_suite(ctx, proposal(ctx), tmp_path / "second", prior_suites=[first])
    assert second["ready"] == 2  # repeats explicitly allowed; no silent resampling
    third = b.compile_suite(ctx, proposal(ctx), tmp_path / "third", prior_suites=[first, second])
    assert third["ready"] == 2
    assert not any(r["status"] == "AXIS_COOLDOWN" for r in third["candidates"])


def test_invalid_execution_not_search_anchor(tmp_path):
    ctx = b.context(observation(valid_execution=False))
    with pytest.raises(ValueError, match="invalid execution"):
        b.compile_suite(ctx, proposal(ctx), tmp_path)


def test_scene_adapter_no_planner_changes():
    assert validate_scene({"box_mass_kg": 1.0}).box_mass_kg == 1.0
    with pytest.raises(ValueError):
        validate_scene({"footprint_radius_m": 0.4})
    with pytest.raises(ValueError):
        validate_scene({"robot_speed": 0.9})
    with pytest.raises(ValueError):
        validate_scene({"box_mass_kg": float("nan")})


def archive(root, *, legacy=False):
    from robot_vlm.task_outcome import GoalEvaluator, task_contract

    root.mkdir()
    protocol = {
        "push_enabled": True,
        "source_hashes": {"runner": "test"},
        "scene_revision": identity(Fixture()),
    }
    result = {"valid_execution": True, "success": False, "reason": "BUDGET_EXHAUSTED"}
    if not legacy:
        contract = task_contract([7.0, 0.0], 10, None)
        protocol.update(
            evaluation_profile="goal_outcome_v1",
            task_contract=contract,
            task_contract_sha256=b.digest(contract),
        )
        condition = {
            k: v for k, v in protocol.items() if k not in {"scene_revision", "scene_config"}
        }
        result.update(
            GoalEvaluator(contract).result("BUDGET_EXHAUSTED", True),
            robot_condition_sha256=b.digest(condition),
            scene_revision=protocol["scene_revision"],
        )
    b.write(root / "protocol.json", protocol)
    b.write(
        root / "result.json",
        result,
    )
    (root / "scene.xml").write_text(world_xml(Fixture()))
    (root / "states.jsonl").write_text(
        json.dumps({"phase": "push", "qpos": [0, 0, 0.74, 1, 0, 0, 0]}) + "\n"
    )
    (root / "decisions.jsonl").write_text("")
    b.write(
        root / "manifest.json",
        {
            "artifacts": [
                {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(root.iterdir())
            ]
        },
    )
    return root


def test_verified_behavior_and_tampering(tmp_path):
    root = archive(tmp_path / "run")
    summary = b.summarize(root)
    assert summary["parameters"]["box_mass_kg"] == 2.0
    assert summary["evidence"][1]["measurement"]["push"]["max_tilt_deg"] == 0.0
    (root / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="artifact mismatch"):
        b.summarize(root)


def test_path_escape_rejected(tmp_path):
    root = archive(tmp_path / "run")
    manifest = b.read(root / "manifest.json")
    manifest["artifacts"][0]["path"] = "../outside"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="unsafe"):
        b.summarize(root)


def test_one_sided_easing_same_axis_and_domain_edge_supported(tmp_path):
    ctx = b.context(observation())
    p = proposal(ctx)
    p.spaces[0].mode = "success_probe"
    p.spaces[0].low, p.spaces[0].high = 0.2, 1.0
    p.spaces[1].axis = "box_mass_kg"
    p.spaces[1].low, p.spaces[1].high = 4.0, 5.0
    suite = b.compile_suite(ctx, p, tmp_path)
    easing = [r for r in suite["candidates"] if r["strategy"] == "success_probe"]
    assert [r["parameters"]["box_mass_kg"] for r in easing] == [0.2, 1.0]
    ctx["latest"]["parameters"]["box_mass_kg"] = 0.2
    p.context_sha256 = b.digest(ctx)
    b.validate(p, ctx)


def test_legacy_evidence_not_reclassified_or_used_for_brackets(tmp_path):
    legacy = b.summarize(archive(tmp_path / "old", legacy=True))
    assert legacy["evaluation_profile"] == "legacy_guarded"
    assert legacy["task_outcome"] == "INCONCLUSIVE"
    ctx = b.context(legacy)
    with pytest.raises(ValueError, match="rerun the scene"):
        b.compile_suite(ctx, proposal(ctx), tmp_path / "new")
    legacy["condition_sha256"] = "same"
    assert not b.brackets(observation(task_outcome="PASS", task_success=True), [legacy])


def test_neighborhood_cooldown_uses_completed_behavior_not_proposal_axis(tmp_path):
    latest = observation(behavior_signature="same-measured-pattern")
    history = [
        observation(run=f"repeat_{i}", behavior_signature="same-measured-pattern") for i in range(2)
    ]
    ctx = b.context(latest, history)
    p = proposal(ctx)
    p.spaces[0].low, p.spaces[0].high = 1.9, 2.1
    suite = b.compile_suite(ctx, p, tmp_path)
    assert sum(r["status"] == "NEIGHBORHOOD_COOLDOWN" for r in suite["candidates"]) == 2
    assert any(
        r["axis"] == "floor_friction" and r["status"] == "READY_FOR_GOAL_RUNNER"
        for r in suite["candidates"]
    )


def test_bracket_repeats_both_sides_and_reports_mixed_results(tmp_path):
    latest = observation()
    success = observation(run="pass", task_outcome="PASS", task_success=True)
    success["parameters"] = {**success["parameters"], "box_mass_kg": 1.0}
    failure = {**success, "run": "same-scene-fail", "task_outcome": "FAIL", "task_success": False}
    ctx = b.context(latest, [success, failure])
    suite = b.compile_suite(ctx, proposal(ctx), tmp_path)
    repeats = [r for r in suite["candidates"] if r["strategy"] == "control_repeat"]
    assert [r["parameters"]["box_mass_kg"] for r in repeats] == [2.0, 1.0]
    assert suite["repeat_statistics"][1]["pass"] == 1
    assert suite["repeat_statistics"][1]["fail"] == 1


def test_single_space_and_nominal_friction_masking(tmp_path):
    ctx = b.context(observation())
    p = proposal(ctx)
    p.spaces = [p.spaces[0]]
    p.spaces[0].axis = "box_friction"
    p.spaces[0].low, p.spaces[0].high = 0.1, 0.2
    suite = b.compile_suite(ctx, p, tmp_path)
    rows = [r for r in suite["candidates"] if r["axis"]]
    assert all(not r["nominal_physics"]["box_floor_sliding_mu_changed"] for r in rows)
