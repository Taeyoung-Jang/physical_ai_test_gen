"""Paired comparison lifecycle: synthetic CPU archives, no paid inference."""

import copy
import json
from pathlib import Path

import pytest

from failure_client.experiments.paired_discovery import (
    PairedDesign,
    PairedDiscovery,
    checked_manifest,
    paired_plan,
)
from failure_client.methods.behavior_feedback import uniform_scene
from llm_afs.behavior import digest

from .test_afs_contrast import Robot, fingerprint
from .test_cause_review import cause_engine
from .test_discovery_continuation import TransferProposer
from .test_independent_discovery import OutcomeRobot


class Proposer(TransferProposer):
    def __call__(self, body, **kwargs):
        response = super().__call__(body, **kwargs)
        response["service_tier"] = "default"
        return response


def setup(tmp_path, *, robot=None, seeds=None, reject=False):
    control = cause_engine(tmp_path)
    data = json.loads(
        (Path(__file__).parents[2] / "config/paired_trajectory_smoke_luna.json").read_text()
    )
    if seeds:
        data["seeds"] = seeds
    frozen = paired_plan(
        [r["source"]["path"] for r in control.plan["history"]],
        PairedDesign.model_validate(data),
        fingerprint_fn=fingerprint,
    )
    root = PairedDiscovery.create(tmp_path / "paired", frozen, fingerprint_fn=fingerprint)
    proposer = Proposer(reject=reject)
    runner = robot or OutcomeRobot("FAIL")
    return (
        PairedDiscovery(root, runner=runner, proposer=proposer, fingerprint_fn=fingerprint),
        proposer,
        runner,
        control,
    )


def test_bootstrap_is_paired_but_evidence_and_cost_are_separate(tmp_path):
    e, p, r, control = setup(tmp_path)
    assert e.summary()["new_attempts"] == 0
    s = e.run(live=True, max_new_attempts=4)
    assert s["new_attempts"] == 4 and not p.calls
    assert r.calls[0] == r.calls[1] and r.calls[2] == r.calls[3]
    first, second = (e.arm(17, method) for method in ("afs", "random"))
    a, b = ({x.evidence_id for x in arm._records()} for arm in (first, second))
    assert not a & b
    assert not (a | b) & {x["evidence_id"] for x in control.plan["history"]}
    assert first.plan["history"] == second.plan["history"] == []
    assert s["comparison"]["relative_gain"] is None
    assert not s["evaluation_complete"]
    candidate, context = second._selection()
    assert context is None
    assert candidate["parameters"] == uniform_scene(
        17, "paired-random-v1", 2, schema=second.cfg.scene_schema
    )


@pytest.mark.parametrize("outcome", ["PASS", "FAIL"])
def test_complete_smoke_uses_latest_afs_and_never_claims_superiority(tmp_path, outcome):
    e, p, r, _ = setup(tmp_path, robot=OutcomeRobot(outcome))
    s = e.run(live=True, max_new_attempts=8, max_new_afs_requests=2)
    assert s["status"] == "COMPLETE" and len(r.calls) == 6
    assert len(p.calls) == 1
    assert s["afs_requests_attempted"] == 1
    assert s["smoke_is_not_target_achievement"]
    assert not s["fixed_budget_observation_available"]
    assert not s["statistical_superiority_established"]
    assert set(s["metrics"]) == {"system_twelve", "original_six"}
    assert len(s["metrics"]["system_twelve"]["groups"]) == 2
    random_ids = {x.evidence_id for x in e.arm(17, "random")._records()}
    refs = {x["id"] for x in p.calls[0]["latest"]["evidence"]}
    assert not refs & random_ids
    report = e.report()
    manifest = json.loads((report.parent / "manifest.json").read_text())
    assert all((report.parent / x["path"]).is_file() for x in manifest["artifacts"])
    audits = json.loads((report.parent / "afs_feedback_audit.json").read_text())
    assert len(audits) == 1 and audits[0]["audit"]["status"] == "VERIFIED_SAVED_REQUEST_CONTEXT"
    assert "복합 징후" in report.read_text()
    assert len(p.calls) == 1 and len(r.calls) == 6
    e.run(live=True, max_new_attempts=8)
    assert len(r.calls) == 6 and len(p.calls) == 1


def test_seeds_are_predeclared_and_isolated(tmp_path):
    e, p, r, _ = setup(tmp_path, seeds=[17, 29])
    s = e.run(live=True, max_new_attempts=16, max_new_afs_requests=4)
    assert s["evaluation_complete"] and len(r.calls) == 12 and len(p.calls) == 2
    first = {x.evidence_id for x in e.arm(17, "afs")._records()}
    second_refs = {x["id"] for x in p.calls[1]["latest"]["evidence"]}
    assert not first & second_refs


def test_exclusion_stops_and_acknowledgement_does_not_replay(tmp_path):
    e, p, r, _ = setup(tmp_path, robot=Robot(excluded=True))
    s = e.run(live=True, max_new_attempts=8)
    assert s["status"] == "NEEDS_ATTENTION" and len(r.calls) == 1
    e.run(live=True, max_new_attempts=8)
    assert len(r.calls) == 1
    e.run(live=True, max_new_attempts=8, continue_after_exclusion=True)
    assert len(r.calls) == 2 and r.calls[0] != r.calls[1]
    assert not p.calls


def test_saved_robot_receipt_is_collected_without_paid_resend(tmp_path):
    e, p, r, _ = setup(tmp_path, robot=Robot(crash=True))
    with pytest.raises(RuntimeError, match="crash after"):
        e.run(live=True)
    assert len(r.calls) == 1
    r.crash = False
    e.run(live=True, max_new_attempts=8)
    assert len(r.calls) == 1
    e.run(live=True)
    assert len(r.calls) == 2 and r.calls[0] == r.calls[1]


def test_rejected_afs_requests_are_bounded_not_random_fallback(tmp_path):
    e, p, r, _ = setup(tmp_path, reject=True)
    e.run(live=True, max_new_attempts=4)
    e.run(live=True, max_new_attempts=4, max_new_afs_requests=1)
    assert len(p.calls) == 1 and len(r.calls) == 4
    s = e.run(live=True, max_new_attempts=4, max_new_afs_requests=1)
    assert len(p.calls) == 2 and len(r.calls) == 4
    assert not s["evaluation_complete"] and s["comparison"]["relative_gain"] is None


def test_saved_proposal_collection_never_resends_or_launches_a_robot(tmp_path):
    e, p, r, _ = setup(tmp_path)
    e.run(live=True, max_new_attempts=4)

    def interrupt(event):
        if event["event"] == "proposal_response_collected":
            raise KeyboardInterrupt("saved response")

    e.on_event = interrupt
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    assert len(p.calls) == 1 and len(r.calls) == 4
    e.on_event = None
    e.run(live=True, max_new_attempts=8)
    assert len(p.calls) == 1 and len(r.calls) == 4
    e.run(live=True, max_new_attempts=8)
    assert len(p.calls) == 1 and len(r.calls) == 6


def test_control_archive_change_stops_before_spending(tmp_path):
    e, p, r, control = setup(tmp_path)
    folder = Path(control.plan["history"][0]["source"]["path"])
    with (folder / "result.json").open("a") as stream:
        stream.write(" ")
    with pytest.raises(ValueError, match="provenance"):
        e.run(live=True)
    assert not p.calls and not r.calls


def test_tampered_totals_and_source_drift_rejected_before_dispatch(tmp_path):
    e, p, r, _ = setup(tmp_path)
    bad = copy.deepcopy(e.wrapped)
    bad["manifest"]["attempt_cap_total"] += 1
    bad["sha256"] = digest(bad["manifest"])
    with pytest.raises(ValueError, match="totals"):
        checked_manifest(bad)
    e.kwargs["fingerprint_fn"] = lambda cfg: {**fingerprint(cfg), "runtime_versions": {"x": "2"}}
    with pytest.raises(ValueError):
        e.run(live=True)
    assert not r.calls and not p.calls


def test_design_rejects_changed_policy_budget_or_seed_selection():
    original = json.loads(
        (Path(__file__).parents[2] / "config/paired_trajectory_smoke_luna.json").read_text()
    )
    for field, value in (("pattern_feedback", "off"), ("max_attempts", 5)):
        data = copy.deepcopy(original)
        data["search"][field] = value
        with pytest.raises(ValueError):
            PairedDesign.model_validate(data)
    original["seeds"] = [17, 17]
    with pytest.raises(ValueError):
        PairedDesign.model_validate(original)
