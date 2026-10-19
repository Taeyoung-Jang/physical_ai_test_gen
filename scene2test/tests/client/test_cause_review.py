"""Evidence-bound model analysis tests; mock-only, no network or physics."""

import copy
import json

import pytest
from jsonschema import validate

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from failure_client.methods.behavior_feedback import NoEligibleEndpoint
from failure_client.methods.cause_review import plan_conflict
from llm_afs import behavior as b
from llm_afs.behavior_request import request

from .test_afs_breadth import broad_engine, point_for_slot
from .test_afs_contrast import fingerprint
from .test_failure_directed import proposal


def reviewed_raw(ctx, *points):
    evidence = {e["id"]: e for e in ctx["latest"]["evidence"]}
    ids = ctx["failure_objective"]["cause_review_contract"]["required_evidence_ids"]
    reviews = [
        {
            "evidence_id": ref,
            "observed_outcome": evidence[ref]["outcome"],
            "observation_versions": [
                a["observation_version"]
                for a in evidence[ref].get("action_timeline", [])[:1]
                if a.get("observation_version") is not None
            ],
            "observed_facts": ["Synthetic fixture: inspect supplied task outcome and actions"],
            "leading_hypothesis": "Navigation may account for noncompletion; not proven",
            "alternative_explanation": "Finite call budget may also matter",
            "uncertainty": "No causal intervention or physical proof",
            "next_test_implication": "Use an admissible scene change, never robot commands",
        }
        for ref in ids
    ]
    points = copy.deepcopy(points)
    for point in points:
        point["analysis_evidence_id"] = ids[0]
        for field in ("behavior_refs", "evidence_refs"):
            if ids[0] not in point[field]:
                point[field].append(ids[0])
        point["measurement_plan"] = {
            "required_observation": "Qualifying temporal evidence under the supplied detector",
            "exclusions_addressed": "Box-only contacts and static no_path do not prove collision",
            "expected_contact_scope": "non_box_world",
        }
    return {**proposal(ctx, *points), "episode_reviews": reviews}


def cause_engine(tmp_path, **kwargs):
    return broad_engine(tmp_path, feedback_policy="cause-review-v2", **kwargs)


def test_rule_capsule_schema_and_host_have_distinct_review_and_prediction(tmp_path):
    e = cause_engine(tmp_path)
    _, ctx = e._selection()
    point, _ = point_for_slot(ctx)
    raw = reviewed_raw(ctx, point)
    body = request(ctx, "gpt-6-luna", selection_policy="autonomous_development_endpoint")
    validate(raw, body["text"]["format"]["schema"])
    schema = body["text"]["format"]["schema"]
    assert list(schema["properties"]) == ["context_sha256", "episode_reviews", "spaces"]
    for definition in [schema, *schema["$defs"].values()]:
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    assert (
        "clear_box_geom"
        in ctx["failure_objective"]["cause_review_contract"]["detectors"]["collision"]["excludes"]
    )
    assert "max_output_tokens" not in body
    assert "SAME response" in body["instructions"]
    candidate = selected_probe(raw, ctx, e._memory())
    assert candidate["selection_audit"]["llm_episode_reviews"] == raw["episode_reviews"]
    assert candidate["evidence"]["analysis_evidence_id"] == raw["episode_reviews"][0]["evidence_id"]
    assert "primary_family" not in candidate["evidence"]
    assert all(
        "detector_observations" in o for o in ctx["failure_objective"]["behavior_observations"]
    )


@pytest.mark.parametrize(
    "bad", ["unknown_id", "outcome", "version", "duplicate", "missing", "link", "extra"]
)
def test_fabricated_references_outcomes_or_schema_stop(tmp_path, bad):
    e = cause_engine(tmp_path)
    _, ctx = e._selection()
    point, _ = point_for_slot(ctx)
    raw = reviewed_raw(ctx, point)
    review = raw["episode_reviews"][0]
    if bad == "unknown_id":
        review["evidence_id"] = "invented"
    elif bad == "outcome":
        review["observed_outcome"] = "FAIL" if review["observed_outcome"] == "PASS" else "PASS"
    elif bad == "version":
        review["observation_versions"] = [999]
    elif bad == "duplicate":
        raw["episode_reviews"].append(copy.deepcopy(review))
    elif bad == "missing":
        raw["episode_reviews"] = raw["episode_reviews"][1:]
    elif bad == "link":
        raw["spaces"][0]["analysis_evidence_id"] = "invented"
    else:
        review["primary_family"] = "collision"
    with pytest.raises(ValueError):
        selected_probe(raw, ctx, e._memory())


def test_collision_box_only_candidate_rejected_without_discarding_valid_alternative(tmp_path):
    e = cause_engine(tmp_path)
    _, ctx = e._selection()
    p, anchor = point_for_slot(ctx)
    q = copy.deepcopy(p)
    low, high = ctx["allowed_axes"][p["axis"]]
    base = anchor["parameters"][p["axis"]]
    delta = 0.15 * (high - low)
    q["value"] = base + delta if base + delta <= high else base - delta
    raw = reviewed_raw(ctx, p, q)
    raw["spaces"][0]["target_family"] = "collision"
    raw["spaces"][0]["measurement_plan"]["expected_contact_scope"] = "box_only"
    chosen = selected_probe(raw, ctx, e._memory())
    assert chosen["space_index"] == 1
    assert any(
        r["reason"] == "collision_plan_excludes_qualifying_world_contact"
        for r in chosen["selection_audit"]["rejected"]
    )
    raw["spaces"] = raw["spaces"][:1]
    with pytest.raises(NoEligibleEndpoint):
        selected_probe(raw, ctx, e._memory())
    assert len(e.state["attempts"]) == 0


def test_old_mode_rejects_reviewed_response_and_new_mode_requires_breadth(tmp_path):
    with pytest.raises(ValueError, match="explicit breadth"):
        SearchBudget(feedback_policy="cause-review-v2")
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    p, _ = point_for_slot(ctx)
    raw = proposal(ctx, p)
    raw["episode_reviews"] = []
    with pytest.raises(ValueError):
        selected_probe(raw, ctx, e._memory())


class ReviewProposer:
    def __init__(self, conflict_first=False):
        self.calls = []
        self.conflict_first = conflict_first

    def __call__(self, body, **kw):
        ctx = json.loads(body["input"][0]["content"])["context"]
        self.calls.append(ctx)
        point, _ = point_for_slot(ctx)
        raw = reviewed_raw(ctx, point)
        if self.conflict_first and len(self.calls) == 1:
            raw["spaces"][0]["target_family"] = "collision"
            raw["spaces"][0]["measurement_plan"]["expected_contact_scope"] = "box_only"
        validate(raw, body["text"]["format"]["schema"])
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


def test_saved_review_resume_no_resend_and_report_preserves_analysis(tmp_path, monkeypatch):
    e = cause_engine(tmp_path, max_attempts=2, valid_rollout_target=2)
    proposer = ReviewProposer()
    e.proposer = proposer

    def crash(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(e, "_finish_proposal", crash)
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    assert len(proposer.calls) == 1 and not e.runner.calls
    resumed = AutonomousAFS(e.root, runner=e.runner, proposer=proposer, fingerprint_fn=fingerprint)
    result = resumed.run(live=True)
    assert result["status"] == "COMPLETE"
    assert len(proposer.calls) == len(e.runner.calls) == 2
    assert "llm_episode_reviews" in resumed.report().read_text()
    assert result["new_only_discovery_metrics"]["groups"][0]["discovered_family_count"] == 0


def test_all_conflicting_proposals_consume_request_not_robot_budget(tmp_path):
    e = cause_engine(tmp_path, max_afs_requests=1)
    e.proposer = ReviewProposer(conflict_first=True)
    result = e.run(live=True)
    assert result["afs_requests_attempted"] == 1
    assert result["attempted"] == 0 and not e.runner.calls
    assert result["afs_proposals_rejected"] == 1


def test_contact_scope_unknown_is_uncertainty_not_automatic_rejection(tmp_path):
    e = cause_engine(tmp_path)
    _, ctx = e._selection()
    p, _ = point_for_slot(ctx)
    raw = reviewed_raw(ctx, p)
    raw["spaces"][0]["target_family"] = "collision"
    raw["spaces"][0]["measurement_plan"]["expected_contact_scope"] = "unknown"
    point = b.ReviewedBreadthProposal.model_validate(raw).spaces[0]
    assert plan_conflict(point) is None
