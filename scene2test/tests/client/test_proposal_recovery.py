"""No API/GPU calls. Explicit repair, frozen conditions, budgets and fault cases."""

import copy
import json
import sqlite3

import pytest

from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.experiments.proposal_recovery import (
    CLAIM,
    corrected_proposal,
    recover_campaign,
)
from failure_client.experiments.research_campaign import NeedsAttention, ResearchCampaign
from failure_client.experiments.research_protocol import CampaignConfig, RobotSettings
from llm_afs import behavior as b

from .test_research_campaign import FakeProposer, frozen, setup


class TypoProposer(FakeProposer):
    def __call__(self, body, **kwargs):
        response = super().__call__(body, **kwargs)
        ctx = json.loads(body["input"][0]["content"])["context"]
        correct = ctx["latest"]["evidence"][0]["id"]
        node = response["output"][0]["content"][0]
        raw = json.loads(node["text"])
        raw["spaces"][0]["evidence_refs"] = [correct[:-1]]
        node["text"] = json.dumps(raw)
        self.spec = {
            "proposal_id": "proposal_00000",
            "replacements": {correct[:-1]: correct},
            "note": "Explicit operator review of single deleted evidence character",
        }
        return response


def stopped(tmp_path):
    cfg = CampaignConfig(
        valid_budget_per_seed=6,
        max_attempts_per_arm=6,
        max_proposals_per_seed=2,
        robot=RobotSettings(model="synthetic-mock"),
    )
    engine, robot, proposer = setup(tmp_path, config=cfg, proposer=TypoProposer())
    engine.run(max_new_attempts=4)
    with pytest.raises(NeedsAttention, match="proposal failed"):
        engine.run(max_new_attempts=1)
    return engine, robot, proposer


def hashes(root):
    return {str(p.relative_to(root)): _hash_file(p) for p in root.rglob("*") if p.is_file()}


def recover(engine, spec, target):
    dry = recover_campaign(engine.root, spec, fingerprint=frozen)
    return recover_campaign(
        engine.root,
        spec,
        output=target,
        apply=True,
        expected_plan_sha256=dry["plan_sha256"],
        fingerprint=frozen,
    )


def test_recovery_preserves_source_budget_cost_and_resume_without_resend(tmp_path):
    engine, robot, proposer = stopped(tmp_path)
    before = hashes(engine.root)
    prior = engine.summary()
    target = tmp_path / "recovered"
    dry = recover_campaign(engine.root, proposer.spec, output=target, fingerprint=frozen)
    assert not dry["applied"] and not target.exists()
    assert hashes(engine.root) == before
    result = recover(engine, proposer.spec, target)
    assert result["applied"] and result["inherited_attempts"] == 4
    assert not result["api_called"] and not result["robot_launched"]
    good_proposer = FakeProposer()
    resumed = ResearchCampaign(target, runner=robot, proposer=good_proposer, fingerprint=frozen)
    summary = resumed.summary()
    for key in (
        "arms",
        "afs_requests_attempted",
        "afs_tokens",
        "robot_tokens",
        "robot_api_calls_observed",
    ):
        assert summary[key] == prior[key]
    assert summary["recovery"]["claim"] == CLAIM
    assert resumed.config == engine.config
    resumed.run(max_new_attempts=0)
    assert len(robot.calls) == 4 and not good_proposer.calls
    resumed.run(max_new_attempts=1)
    assert len(robot.calls) == 5 and not good_proposer.calls
    assert resumed.state["attempts"][-1]["candidate"]["proposal_id"] == "proposal_00000"
    # Finish the synthetic pilot: old costs remain charged, old results not rerun.
    resumed.run()
    assert resumed.summary()["status"] == "COMPLETE"
    assert len(robot.calls) == 12
    assert resumed.summary()["afs_requests_attempted"] <= 2
    report = resumed.report(with_memory=True)
    metrics = read_json(report.parent / "metrics.json")
    assert metrics["comparison"]["status"] == "not_comparable"
    assert metrics["comparison"]["relative_gain"] is None
    assert metrics["comparison"]["per_seed"] == []
    assert "operator_assisted_recovery" in metrics["comparison"]["issues"]
    assert (report.parent / "recovery.json").is_file()
    assert hashes(engine.root) == before
    assert read_json(target / "proposals/proposal_00000/response.json") == read_json(
        engine.root / "proposals/proposal_00000/response.json"
    )


def test_error_records_unknown_and_allowed_ids(tmp_path):
    engine, _, proposer = stopped(tmp_path)
    error = read_json(engine.root / "proposals/proposal_00000/error.json")
    diagnostic = error["validation"]
    assert diagnostic["code"] == "unknown_evidence_reference"
    assert diagnostic["unknown"] == list(proposer.spec["replacements"])
    assert next(iter(proposer.spec["replacements"].values())) in diagnostic["allowed"]


def test_committed_wal_is_read_without_modifying_source(tmp_path):
    engine, _, proposer = stopped(tmp_path)
    db = sqlite3.connect(engine.root / "campaign.sqlite3")
    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA wal_autocheckpoint=0")
        db.execute("UPDATE research_state SET payload=payload WHERE id=1")
        db.commit()
        before = hashes(engine.root)
        plan = recover_campaign(engine.root, proposer.spec, fingerprint=frozen)
        assert plan["plan"]["inherited_attempts"] == 4
        assert hashes(engine.root) == before
    finally:
        db.close()


def test_recovered_source_evidence_change_blocks_launch(tmp_path):
    engine, robot, proposer = stopped(tmp_path)
    target = tmp_path / "fork"
    recover(engine, proposer.spec, target)
    afs = next(a for a in engine.state["attempts"] if a["method"] == "afs")
    (engine.root / "attempts" / afs["id"] / "rollout/result.json").write_text("{}")
    recovered = ResearchCampaign(target, runner=robot, fingerprint=frozen)
    with pytest.raises(NeedsAttention, match="evidence changed"):
        recovered.run(max_new_attempts=1)
    assert len(robot.calls) == 4


@pytest.mark.parametrize("mutation", ["wrong", "multiple", "valid", "empty"])
def test_mapping_cannot_invent_or_replace_valid_evidence(tmp_path, mutation):
    engine, _, proposer = stopped(tmp_path)
    spec = copy.deepcopy(proposer.spec)
    old = next(iter(spec["replacements"]))
    if mutation == "wrong":
        spec["replacements"][old] = "f" * 64
    elif mutation == "multiple":
        spec["replacements"]["e" * 63] = "e" * 64
    elif mutation == "valid":
        spec["replacements"] = {"case_memory": "observed_brackets"}
    else:
        spec["replacements"] = {}
    with pytest.raises(ValueError):
        recover_campaign(engine.root, spec, fingerprint=frozen)


def test_ambiguous_reference_and_other_schema_errors_rejected():
    old = "a" * 63
    ctx = {"latest": {"evidence": [{"id": "a" * 64}, {"id": "b" + old}]}}
    raw = {
        "context_sha256": b.digest(ctx),
        "spaces": [
            {
                "mode": "success_probe",
                "axis": "box_mass_kg",
                "low": 0.3,
                "high": 2.0,
                "evidence_refs": [old],
                "hypothesis": "h",
                "alternative": "a",
                "falsification": "f",
            }
        ],
    }
    with pytest.raises(ValueError, match="unique"):
        corrected_proposal(raw, ctx, {old: "a" * 64})


@pytest.mark.parametrize("mutation", ["stale_context", "range", "response_usage", "evidence"])
def test_changed_evidence_or_other_bad_response_not_repaired(tmp_path, mutation):
    engine, _, proposer = stopped(tmp_path)
    path = engine.root / "proposals/proposal_00000/response.json"
    response = read_json(path)
    if mutation == "evidence":
        (engine.root / "attempts/attempt_00000/rollout/result.json").write_text("{}")
    else:
        raw = json.loads(response["output"][0]["content"][0]["text"])
        if mutation == "stale_context":
            raw["context_sha256"] = "b" * 64
        elif mutation == "range":
            raw["spaces"][0]["high"] = 9999.0
        else:
            response["usage"]["input_tokens"] += 1
        response["output"][0]["content"][0]["text"] = json.dumps(raw)
        path.write_text(json.dumps(response))
    with pytest.raises(ValueError):
        recover_campaign(engine.root, proposer.spec, fingerprint=frozen)


def test_source_lock_and_review_hash_enforced(tmp_path):
    engine, _, proposer = stopped(tmp_path)
    with engine.store.exclusive():
        with pytest.raises(ValueError, match="active"):
            recover_campaign(engine.root, proposer.spec, fingerprint=frozen)
    target = tmp_path / "fork"
    with pytest.raises(ValueError, match="plan changed"):
        recover_campaign(
            engine.root,
            proposer.spec,
            output=target,
            apply=True,
            expected_plan_sha256="0" * 64,
            fingerprint=frozen,
        )
    assert not target.exists()
    with pytest.raises(ValueError, match="requires"):
        recover_campaign(engine.root, proposer.spec, output=target, apply=True, fingerprint=frozen)
    with pytest.raises(ValueError, match="new and disjoint"):
        recover_campaign(
            engine.root, proposer.spec, output=engine.root / "fork", fingerprint=frozen
        )


@pytest.mark.parametrize("changed", ["robot_resources", "source_hashes", "runtime_versions"])
def test_unrelated_environment_drift_not_permitted(tmp_path, changed):
    engine, _, proposer = stopped(tmp_path)
    changed_environment = {**frozen(None), changed: {"src/robot_vlm/goal_runner.py": "bad"}}
    with pytest.raises(ValueError, match="changed|drift"):
        recover_campaign(engine.root, proposer.spec, fingerprint=lambda _: changed_environment)


@pytest.mark.parametrize(
    "file",
    [
        "recovery.json",
        "source_snapshot.json",
        "proposals/proposal_00000/response.json",
        "proposals/proposal_00000/request.json",
    ],
)
def test_tampered_recovery_artifacts_prevent_resume(tmp_path, file):
    engine, robot, proposer = stopped(tmp_path)
    target = tmp_path / "fork"
    recover(engine, proposer.spec, target)
    path = target / file
    value = read_json(path)
    value["tampered"] = True
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="mismatch|changed"):
        ResearchCampaign(target, runner=robot, fingerprint=frozen)
    assert len(robot.calls) == 4
