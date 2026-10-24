"""AFS-only assessment/reporting with synthetic archives; no network/GPU/policy."""

import copy
import hashlib
import json
import runpy
from pathlib import Path

import pytest

from failure_client.experiments.paired_discovery import PairedDesign, PairedDiscovery, paired_plan
from failure_client.reporting.humanoid_assessment import (
    build_summary,
    export_summary,
    snapshot,
    terminal,
)

from .test_afs_contrast import fingerprint
from .test_independent_discovery import OutcomeRobot
from .test_matched_local import LocalProposer, setup_local

PROJECT = Path(__file__).parents[2]


class AssessmentRobot(OutcomeRobot):
    def __call__(self, cfg, directory, params):
        self.outcome = "PASS" if not self.calls else "FAIL"
        return super().__call__(cfg, directory, params)


def setup_assessment(tmp_path, *, robot=None, proposer=None):
    template, _, _ = setup_local(tmp_path)
    data = template.design.model_dump()
    data.update(
        purpose="robot-vulnerability-assessment",
        methods=["afs"],
        valid_per_arm=4,
        attempts_per_arm=4,
        afs_requests_per_seed=5,
    )
    data["search"].update(valid_rollout_target=4, max_attempts=4, max_afs_requests=5)
    paths = [r["source"]["path"] for r in template.manifest["control_provenance"]]
    frozen = paired_plan(paths, PairedDesign.model_validate(data), fingerprint_fn=fingerprint)
    root = PairedDiscovery.create(tmp_path / "assessment", frozen, fingerprint_fn=fingerprint)
    robot, proposer = robot or AssessmentRobot(), proposer or LocalProposer()

    def factory(path, on_event=None):
        return PairedDiscovery(
            path, runner=robot, proposer=proposer, fingerprint_fn=fingerprint, on_event=on_event
        )

    return root, robot, proposer, factory


def cli():
    return runpy.run_path(str(PROJECT / "tools/run_humanoid_assessment.py"))["main"]


def test_afs_only_caps_no_random_and_shared_local_contract(tmp_path):
    root, robot, proposer, factory = setup_assessment(tmp_path)
    engine = factory(root)
    assert engine.manifest["valid_total"] == engine.manifest["attempt_cap_total"] == 4
    assert engine.manifest["robot_api_call_upper_bound"] == 40
    assert engine.random_schedule() == []
    assert not (root / "seeds/17/random").exists()
    summary = engine.run(live=True, max_new_attempts=4, max_new_afs_requests=5)
    assert summary["status"] == "COMPLETE"
    assert summary["comparison"]["status"] == "not_requested_assessment"
    assert len(robot.calls) == 4 and len(proposer.calls) == 3
    base = engine.design.matched_local["base_parameters"]
    assert [sum(v != base[a] for a, v in p.items()) for p in robot.calls] == [0, 1, 2, 1]
    assert engine.domain_geometry_audit()["planned_random_slots_including_unused"] == 0


def test_cli_outputs_each_result_and_final_report_without_extra_api(tmp_path, capsys):
    root, robot, proposer, factory = setup_assessment(tmp_path)
    result = cli()(["run", "--assessment", str(root), "--live"], factory=factory)
    assert result == 0
    output = capsys.readouterr().out
    assert output.count("테스트 결과:") == 4
    assert "유효 4/4" in output and "PASS 1 / FAIL 3 / 제외 0" in output
    assert "원인" in output and "REPORT=" in output
    assert "최종 검증 전 핵심 결과" in output
    folders = list((root / "assessment_reports").iterdir())
    report = json.loads((folders[0] / "summary.json").read_text())
    assert report["complete"] and report["fail"] == 3
    assert len(robot.calls) == 4 and len(proposer.calls) == 3

    def forbidden(*_, **__):
        raise AssertionError("completed assessment must not dispatch or initialize a runner")

    assert cli()(["run", "--assessment", str(root), "--live"], factory=forbidden) == 0
    assert len(robot.calls) == 4 and len(proposer.calls) == 3


def test_proposal_error_keeps_pending_and_prints_partial_summary(tmp_path, capsys):
    def broken(*_, **__):
        raise RuntimeError("synthetic API failure")

    root, robot, _, factory = setup_assessment(tmp_path, proposer=broken)
    assert cli()(["run", "--assessment", str(root), "--live"], factory=factory) == 2
    output = capsys.readouterr().out
    assert "유효 1/4" in output and "미완료 제안 요청" in output
    assert "synthetic API failure" in output
    assert len(robot.calls) == 1
    m, states = snapshot(root)
    assert states[0]["pending"] == {"kind": "proposal", "index": 0}
    summary = build_summary(root, m, states)
    assert summary["fail"] == summary["excluded"] == 0
    assert summary["afs_requests"] == 1


def test_baseline_fail_stops_and_is_not_a_completed_assessment(tmp_path, capsys):
    root, robot, proposer, factory = setup_assessment(tmp_path, robot=OutcomeRobot("FAIL"))
    assert cli()(["run", "--assessment", str(root), "--live"], factory=factory) == 2
    output = capsys.readouterr().out
    assert "BASELINE_NOT_CONFIRMED" in output
    assert len(robot.calls) == 1 and not proposer.calls


def test_zero_budget_and_no_live_never_dispatch(tmp_path, capsys):
    root, robot, proposer, factory = setup_assessment(tmp_path)
    assert cli()(["run", "--assessment", str(root)], factory=factory) == 2
    assert "--live" in capsys.readouterr().out
    assert (
        cli()(
            ["run", "--assessment", str(root), "--live", "--max-new-attempts", "0"], factory=factory
        )
        == 2
    )
    assert not robot.calls and not proposer.calls
    assert "1 이상" in capsys.readouterr().out


def test_unknown_safety_is_not_zero_and_pass_event_not_goal_failure(tmp_path):
    root, _, _, factory = setup_assessment(tmp_path)
    factory(root).run(live=True, max_new_attempts=1)
    manifest, states = snapshot(root)
    partial = build_summary(root, manifest, states)
    assert partial["safety"]["unknown"] == 1 and partial["safety"]["events"] is None
    episode = states[0]["attempts"][0]["episode"]
    measurement = {
        "evidence_id": episode["evidence_id"],
        "task_outcome": "PASS",
        "measurement_status": "AVAILABLE",
        "safety_event_detected": True,
        "evidence_binding": "VERIFIED_ARCHIVE_DYNAMIC_SCENE_BASE_AND_CONTACT_TRACE",
    }
    canonical = {
        "dynamic_human_safety": {
            "arms": [
                {"evidence": [{"evidence_id": episode["evidence_id"], "measurement": measurement}]}
            ]
        }
    }
    result = build_summary(root, manifest, states, canonical=canonical)
    assert result["pass"] == 1 and result["fail"] == 0
    assert result["safety"]["events"] == 1 and not result["family_counts"]
    wrong = copy.deepcopy(canonical)
    wrong["dynamic_human_safety"]["arms"][0]["evidence"][0]["measurement"]["task_outcome"] = "FAIL"
    assert build_summary(root, manifest, states, canonical=wrong)["safety"]["unknown"] == 1


def test_report_rejects_tampered_result_and_escapes_html(tmp_path):
    root, _, _, factory = setup_assessment(tmp_path)
    factory(root).run(live=True, max_new_attempts=1)
    m, states = snapshot(root)
    s = build_summary(root, m, states, error={"type": "example", "message": "<script>bad</script>"})
    assert s["status"] == "NEEDS_ATTENTION"
    assert "목표 실패 미검출" in terminal(s)
    report = export_summary(tmp_path / "report", s)
    assert "<script>bad</script>" not in report.read_text()
    assert "&lt;script&gt;" in report.read_text()
    for row in json.loads((report.parent / "manifest.json").read_text())["artifacts"]:
        assert (
            hashlib.sha256((report.parent / row["path"]).read_bytes()).hexdigest() == row["sha256"]
        )
    archive = Path(states[0]["attempts"][0]["episode"]["source"]["path"])
    (archive / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="core evidence"):
        snapshot(root)


def test_config_is_ten_total_afs_only_and_random_is_refused():
    data = json.loads((PROJECT / "config/humanoid_vulnerability_10_pro.json").read_text())
    design = PairedDesign.model_validate(data)
    assert design.methods == ["afs"]
    assert design.valid_per_arm == design.attempts_per_arm == 10
    assert design.cold_start_per_arm == 1
    for methods in (["random"], ["afs", "random"]):
        bad = copy.deepcopy(data)
        bad["methods"] = methods
        with pytest.raises(ValueError, match="assessment"):
            PairedDesign.model_validate(bad)


def test_excluded_execution_is_not_robot_failure_or_safe_result(tmp_path):
    from .test_afs_contrast import Robot

    root, robot, proposer, factory = setup_assessment(tmp_path, robot=Robot(excluded=True))
    factory(root).run(live=True, max_new_attempts=4)
    m, states = snapshot(root)
    summary = build_summary(root, m, states)
    assert summary["valid"] == summary["fail"] == 0 and summary["excluded"] == 1
    assert summary["safety"]["events"] is None
    assert not summary["family_counts"] and not summary["complete"]
    assert len(robot.calls) == 1 and not proposer.calls


def test_stale_or_modified_safety_cache_is_not_reused(tmp_path):
    root, _, _, factory = setup_assessment(tmp_path)
    functions = runpy.run_path(str(PROJECT / "tools/run_humanoid_assessment.py"))
    functions["main"](
        ["run", "--assessment", str(root), "--live", "--max-new-attempts", "1"], factory=factory
    )
    _, states = snapshot(root)
    assert functions["cached_measurements"](root, states) is not None
    altered = copy.deepcopy(states)
    altered[0]["reason"] = "different checkpoint"
    assert functions["cached_measurements"](root, altered) is None
    path = root / "assessment_measurements.json"
    value = json.loads(path.read_text())
    value["value"]["canonical"]["dynamic_human_safety"] = {"arms": []}
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="cache digest"):
        functions["cached_measurements"](root, states)


def test_inconsistent_primary_attribution_never_gets_family_credit(tmp_path):
    root, _, _, factory = setup_assessment(tmp_path)
    factory(root).run(live=True, max_new_attempts=2)
    m, states = snapshot(root)
    episode = states[0]["attempts"][1]["episode"]
    episode["attribution"] = {"primary_family": "fall", "rule_version": "unverified-rule"}
    episode["taxonomy"]["families"]["fall"]["status"] = "NOT_DETECTED"
    summary = build_summary(root, m, states)
    assert summary["fail"] == 1 and not summary["family_counts"]
    assert summary["cases"][1]["primary_family"] is None
