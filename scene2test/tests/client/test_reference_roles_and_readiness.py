"""Role separation, constrained recovery and honest evaluation preparation; CPU only."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import validate

from failure_client.evaluation.discovery_readiness import audit_discovery
from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.experiments.anchor_ref_recovery import (
    normalize_anchor_refs,
    recover_anchor_refs,
)
from failure_client.experiments.discovery_evaluation import EvaluationDesign, evaluation_plan
from failure_client.methods.autonomous_feedback import selected_probe
from llm_afs.behavior_request import request

from .test_afs_breadth import point_for_slot
from .test_afs_contrast import fingerprint
from .test_cause_review import cause_engine, reviewed_raw


def test_separate_pass_anchor_and_fail_analysis_is_valid(tmp_path):
    e = cause_engine(tmp_path)
    e.state["lock"]["plan"]["budget"]["feedback_policy"] = "cause-review-v3"
    _, ctx = e._selection()
    p, anchor = point_for_slot(ctx)
    raw = reviewed_raw(ctx, p)
    for s in raw["spaces"]:
        s["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
        s["behavior_refs"] = [s["analysis_evidence_id"]]
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    validate(raw, body["text"]["format"]["schema"])
    assert (
        "behavior_refs must include actual episode evidence from the selected anchor"
        not in body["instructions"]
    )
    chosen = selected_probe(raw, ctx, e._memory())
    assert chosen["selection_audit"]["anchor_evidence_id"] == anchor["evidence_ids"][0]
    assert "domain_constraints" in ctx["failure_objective"]
    raw["spaces"][0]["anchor_behavior_refs"] = raw["spaces"][0]["behavior_refs"]
    with pytest.raises(ValueError, match="anchor_behavior_refs"):
        selected_probe(raw, ctx, e._memory())


def test_repair_only_adds_already_declared_unique_anchor_ref(tmp_path):
    e = cause_engine(tmp_path)
    _, ctx = e._selection()
    p, anchor = point_for_slot(ctx)
    raw = reviewed_raw(ctx, p)
    raw["spaces"][0]["behavior_refs"] = [raw["spaces"][0]["analysis_evidence_id"]]
    before = copy.deepcopy(raw)
    fixed = normalize_anchor_refs(raw, ctx)
    assert raw == before
    assert (
        fixed["spaces"][0]["behavior_refs"]
        == before["spaces"][0]["behavior_refs"] + anchor["evidence_ids"][:1]
    )
    assert selected_probe(fixed, ctx, e._memory())
    raw["spaces"][0]["evidence_refs"].remove(anchor["evidence_ids"][0])
    with pytest.raises(ValueError, match="already-cited"):
        normalize_anchor_refs(raw, ctx)


class MissingAnchor:
    def __call__(self, body, **kw):
        ctx = json.loads(body["input"][0]["content"])["context"]
        p, _ = point_for_slot(ctx)
        raw = reviewed_raw(ctx, p)
        raw["spaces"][0]["behavior_refs"] = [raw["spaces"][0]["analysis_evidence_id"]]
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        }


def test_recovery_fork_preserves_source_budget_costs_and_normalized_response(tmp_path):
    e = cause_engine(tmp_path)
    e.proposer = MissingAnchor()
    with pytest.raises(ValueError, match="selected anchor"):
        e.run(live=True)
    before = {
        str(p.relative_to(e.root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in e.root.rglob("*")
        if p.is_file()
    }
    output = tmp_path / "recovery"
    dry = recover_anchor_refs(e.root, output, fingerprint_fn=fingerprint)
    assert not dry["applied"] and not output.exists()
    applied = recover_anchor_refs(e.root, output, apply=True, fingerprint_fn=fingerprint)
    assert applied["summary"]["afs_requests_attempted"] == 1
    assert applied["audit"]["budget_reset"] is False
    assert applied["summary"]["attempted"] == 0
    assert before == {
        str(p.relative_to(e.root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in e.root.rglob("*")
        if p.is_file()
    }
    resumed = AutonomousAFS(
        output,
        runner=e.runner,
        proposer=lambda *a, **k: pytest.fail("no resend"),
        fingerprint_fn=fingerprint,
    )
    resumed.run(live=True, max_new_attempts=1)
    assert len(e.runner.calls) == 1
    (output / "source_state.json").write_text("{}")
    with pytest.raises(ValueError, match="snapshot"):
        AutonomousAFS(output, fingerprint_fn=fingerprint)


def test_human_near_goal_exposure_incompatibility_is_not_global_impossibility():
    audit = audit_discovery("clear-path-human-v5")
    h = audit["human_goal_compatibility"]
    assert h["simultaneous_inside_goal_and_exposure"] == "PROVEN_DISJOINT"
    assert h["goal_disk_to_exposure_lower_gap_m"] == pytest.approx(1.4)
    assert audit["supported_rule_count"] == 8
    assert len(audit["families"]) == 10
    assert all(f["attainability"] == "NOT_PROVEN" for f in audit["families"])
    assert not audit["observations_by_condition"]


def design():
    path = Path(__file__).resolve().parents[2] / "config/discovery_evaluation_luna.json"
    return EvaluationDesign.model_validate(json.loads(path.read_text()))


def test_evaluation_preparation_never_uses_development_warm_history(tmp_path):
    e = cause_engine(tmp_path)
    paths = [Path(r["source"]["path"]) for r in e.plan["history"]]
    result = evaluation_plan(paths, design(), fingerprint_fn=fingerprint)
    m = result["manifest"]
    assert m["external_history_in_evaluation"] == []
    assert m["valid_total"] == 60 and m["attempt_cap_total"] == 72
    assert m["robot_api_call_upper_bound"] == 720
    assert m["execution_readiness"] == "INDEPENDENT_RUNNER_IMPLEMENTED_NOT_LIVE_VALIDATED"
    assert len(m["control_provenance"]) == 2
    assert not e.runner.calls


def test_evaluation_rejects_seed_cherry_pick_and_budget_mismatch():
    d = design().model_dump()
    d["seeds"] = [17, 17]
    with pytest.raises(ValueError):
        EvaluationDesign.model_validate(d)
    d = design().model_dump()
    d["search"]["max_attempts"] = 25
    with pytest.raises(ValueError):
        EvaluationDesign.model_validate(d)
