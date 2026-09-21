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
    assert suite["ready"] == 7
    for row in suite["candidates"]:
        validate_scene(b.read(row["config"]))
        if row["axis"]:
            changed = [k for k in b.AXES if row["parameters"][k] != ctx["latest"]["parameters"][k]]
            assert changed == [row["axis"]]
    assert suite["brackets"] == []
    assert len([r for r in suite["candidates"] if r["strategy"] == "independent_exploration"]) == 2


@pytest.mark.parametrize("change", ["one_sided", "same_axis", "no_evidence", "stale"])
def test_bad_proposals_rejected(change):
    ctx = b.context(observation())
    p = proposal(ctx)
    if change == "one_sided":
        p.spaces[0].low = 2.5
    elif change == "same_axis":
        p.spaces[1].axis = "box_mass_kg"
    elif change == "no_evidence":
        p.spaces[0].evidence_refs = ["invented"]
    else:
        p.context_sha256 = "old"
    with pytest.raises(ValueError):
        b.validate(p, ctx)


def test_bracket_requires_opposite_comparable_task_outcomes(tmp_path):
    a = observation()
    other = copy.deepcopy(a)
    other["parameters"]["box_mass_kg"] = 1.0
    assert not b.brackets(a, [other])
    other["task_success"] = True
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


def test_dedup_and_axis_cooldown(tmp_path):
    ctx = b.context(observation())
    first = b.compile_suite(ctx, proposal(ctx), tmp_path / "first")
    second = b.compile_suite(ctx, proposal(ctx), tmp_path / "second", prior_suites=[first])
    assert second["ready"] == 1  # repeat explicitly allowed; no silent resampling
    third = b.compile_suite(ctx, proposal(ctx), tmp_path / "third", prior_suites=[first, second])
    assert sum(r["status"] == "AXIS_COOLDOWN" for r in third["candidates"]) == 2


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


def archive(root):
    root.mkdir()
    protocol = {
        "push_enabled": True,
        "source_hashes": {"runner": "test"},
        "scene_revision": identity(Fixture()),
    }
    b.write(root / "protocol.json", protocol)
    b.write(
        root / "result.json",
        {"valid_execution": True, "success": False, "reason": "BUDGET_EXHAUSTED"},
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
