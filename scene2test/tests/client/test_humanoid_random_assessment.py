"""Standalone Random script: local draws, zero proposer, durable CPU test doubles."""

import copy
import hashlib
import json
import runpy
from pathlib import Path

import pytest

from failure_client.methods.matched_local import check_candidate, random_candidate

from .test_afs_contrast import Robot, fingerprint
from .test_humanoid_assessment import setup_assessment
from .test_independent_discovery import OutcomeRobot

PROJECT = Path(__file__).parents[2]


def functions():
    return runpy.run_path(str(PROJECT / "tools/run_humanoid_random_assessment.py"))


def setup_random(tmp_path, *, robot=None, count=4):
    afs_root, _, _, afs_factory = setup_assessment(tmp_path)
    afs = afs_factory(afs_root)
    f = functions()
    data = afs.design.model_dump()
    data.update(
        schema_version="humanoid-random-assessment-design-v1",
        purpose=f["PURPOSE"],
        methods=["random"],
        afs_requests_per_seed=0,
    )
    data["search"]["max_afs_requests"] = 1
    data.update(valid_per_arm=count, attempts_per_arm=count)
    data["search"].update(valid_rollout_target=count, max_attempts=count)
    design = f["RandomDesign"].model_validate(data)
    paths = [c["source"]["path"] for c in afs.manifest["control_provenance"]]
    frozen = f["plan"](paths, design, fingerprint_fn=fingerprint)
    root = f["RandomAssessment"].create(tmp_path / "random", frozen, fingerprint_fn=fingerprint)
    robot = robot or OutcomeRobot("PASS")
    proposer_calls = []

    def proposer(*args, **kwargs):
        proposer_calls.append((args, kwargs))
        raise AssertionError("Random must never use a proposer")

    def factory(path, on_event=None):
        return f["RandomAssessment"](
            path, runner=robot, proposer=proposer, fingerprint_fn=fingerprint, on_event=on_event
        )

    return root, robot, proposer_calls, factory, f


def test_random_only_complete_never_calls_proposer_and_uses_same_base(tmp_path):
    root, robot, calls, factory, f = setup_random(tmp_path, count=10)
    e = factory(root)
    assert e.manifest["valid_total"] == e.manifest["attempt_cap_total"] == 10
    assert e.manifest["robot_api_call_upper_bound"] == 100
    assert e.manifest["afs_request_upper_bound"] == 0
    assert not (root / "seeds/17/afs").exists()
    result = e.run(live=True, max_new_attempts=10)
    assert result["status"] == "COMPLETE" and result["afs_requests_attempted"] == 0
    assert len(robot.calls) == 10 and not calls
    for index, params in enumerate(robot.calls):
        check_candidate(
            params,
            e.design.matched_local,
            e.design.scene_domain,
            0 if index == 0 else 1 + (index - 1) % 2,
            0.1,
        )
        if index:
            assert (
                params
                == random_candidate(
                    e.design.matched_local, e.design.scene_domain, 0.1, 17, index - 1
                )["parameters"]
            )
    m, states = f["snapshot"](root)
    assert m["methods"] == ["random"] and not states[0]["proposals"]
    before = copy.deepcopy(robot.calls)
    e.run(live=True, max_new_attempts=4)
    assert robot.calls == before


def test_selection_does_not_accumulate_or_use_outcomes(tmp_path):
    root, _, _, factory, _ = setup_random(tmp_path)
    e = factory(root)
    e.run(live=True, max_new_attempts=1)
    arm = e.arm(17, "random")
    expected = arm._selection()
    arm.state["attempts"][0]["episode"]["task_outcome"] = "FAIL"
    arm.state["attempts"][0]["candidate"]["parameters"] = {}
    assert arm._selection() == expected


def test_saved_receipt_collection_never_reexecutes(tmp_path):
    robot = Robot(crash=True)
    root, _, calls, factory, _ = setup_random(tmp_path, robot=robot)
    with pytest.raises(RuntimeError, match="crash after"):
        factory(root).run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 1
    robot.crash = False
    factory(root).run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 1 and not calls
    factory(root).run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 2


def test_baseline_exclusion_stops_and_is_not_a_failure(tmp_path):
    root, robot, calls, factory, f = setup_random(tmp_path, robot=Robot(excluded=True))
    result = factory(root).run(live=True, max_new_attempts=4)
    assert result["status"] == "BASELINE_NOT_CONFIRMED"
    value = f["summary"](root, canonical=result)
    assert value["valid"] == value["fail"] == 0 and value["excluded"] == 1
    assert value["afs_requests"] == 0 and value["safety"]["events"] is None
    factory(root).run(live=True, max_new_attempts=4, continue_after_exclusion=True)
    assert len(robot.calls) == 1 and not calls


def test_cli_immediate_output_reports_and_completed_no_dispatch(tmp_path, capsys):
    root, robot, calls, factory, f = setup_random(tmp_path)
    assert f["main"](["run", "--assessment", str(root), "--live"], factory=factory) == 0
    output = capsys.readouterr().out
    assert output.count("Random 결과:") == 4
    assert "AFS 제안 0회" in output and "유효 4/4" in output and "REPORT=" in output
    report = next((root / "assessment_reports").iterdir())
    value = json.loads((report / "summary.json").read_text())
    assert value["complete"] and value["method"] == "random" and value["afs_requests"] == 0
    assert "Random 전용 평가" in (report / "report.html").read_text()
    for row in json.loads((report / "manifest.json").read_text())["artifacts"]:
        assert hashlib.sha256((report / row["path"]).read_bytes()).hexdigest() == row["sha256"]

    def forbidden(*_, **__):
        raise AssertionError("completed report must never create a runner")

    assert f["main"](["run", "--assessment", str(root), "--live"], factory=forbidden) == 0
    assert len(robot.calls) == 4 and not calls


def test_cli_live_guard_and_zero_budget_preserve_empty_state(tmp_path, capsys):
    root, robot, calls, factory, f = setup_random(tmp_path)
    assert f["main"](["run", "--assessment", str(root)], factory=factory) == 2
    assert "--live" in capsys.readouterr().out
    assert (
        f["main"](
            ["run", "--assessment", str(root), "--live", "--max-new-attempts", "0"], factory=factory
        )
        == 2
    )
    assert not robot.calls and not calls
    assert not f["snapshot"](root)[1][0]["attempts"]


def test_budget_tamper_and_foreign_afs_assessment_are_rejected(tmp_path):
    root, _, _, _, f = setup_random(tmp_path)
    frozen = json.loads((root / "manifest.json").read_text())
    frozen["manifest"]["afs_request_upper_bound"] = 1
    from llm_afs.behavior import digest

    frozen["sha256"] = digest(frozen["manifest"])
    with pytest.raises(ValueError, match="budget"):
        f["checked_manifest"](frozen)
    with pytest.raises(ValueError, match="manifest"):
        f["snapshot"](tmp_path / "assessment")
    episode_root = root / "seeds/17/random"
    from failure_client.storage.research_store import ResearchStore

    store = ResearchStore(episode_root)
    state, revision = store.load()
    state["proposals"].append({"id": "forbidden"})
    store.save(state, revision, "synthetic_tamper")
    with pytest.raises(ValueError, match="proposer"):
        f["snapshot"](root)


def test_production_config_has_ten_robot_attempts_and_zero_afs():
    f = functions()
    random = f["RandomDesign"].model_validate(
        json.loads((PROJECT / "config/humanoid_random_vulnerability_10_pro.json").read_text())
    )
    afs = json.loads((PROJECT / "config/humanoid_vulnerability_10_pro.json").read_text())
    assert random.methods == ["random"] and random.afs_requests_per_seed == 0
    assert random.valid_per_arm == random.attempts_per_arm == 10
    assert random.cold_start_per_arm == 1
    assert random.matched_local == afs["matched_local"]
    assert random.scene_domain["axes"] == afs["scene_domain"]["axes"]
    assert random.seeds == afs["seeds"]
