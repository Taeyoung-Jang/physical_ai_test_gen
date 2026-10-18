"""Synthetic end-to-end ten-type feedback; no paid policy or simulation execution."""

import json

import pytest
from jsonschema import validate

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from llm_afs.behavior_request import request

from .test_afs_contrast import fingerprint
from .test_branch_anchors import branch_point, engine
from .test_failure_directed import proposal


@pytest.mark.parametrize(
    "family", ["fall", "locomotion_stall", "manipulation_failure", "goal_completion_failure"]
)
def test_new_targets_match_schema_and_host_only_when_enabled(tmp_path, family):
    e = engine(tmp_path, taxonomy_profile="expanded-ten-v1")
    _, ctx = e._selection()
    p, _ = branch_point(ctx)
    p["target_family"] = family
    raw = proposal(ctx, p)
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    validate(raw, body["text"]["format"]["schema"])
    assert selected_probe(raw, ctx, e._memory())["evidence"]["target_family"] == family
    objective = ctx["failure_objective"]
    assert objective["family_denominator"] == 10
    assert "unreachable" not in objective["supported_targets"]
    assert "perception_error" not in objective["supported_targets"]
    assert "WHOLE" in body["instructions"] and "actual execution" in body["instructions"]
    assert "max_output_tokens" not in body
    old_ctx = json.loads(json.dumps(ctx))
    old_ctx["development_search"]["budget"]["taxonomy_profile"] = "scene-default"
    with pytest.raises(ValueError):
        selected_probe(proposal(old_ctx, p), old_ctx, e._memory())


def test_measured_family_feedback_deprioritizes_known_type_not_predicted_type(
    tmp_path, monkeypatch
):
    import failure_client.evaluation.expanded_taxonomy as taxonomy

    # Synthetic detector wiring fixture, not evidence about physical goal completion.
    monkeypatch.setattr(
        taxonomy,
        "new_observations",
        lambda *a, **kw: (
            {
                "fall": "NOT_DETECTED",
                "locomotion_stall": "NOT_DETECTED",
                "manipulation_failure": "NOT_DETECTED",
                "goal_completion_failure": "DETECTED",
            },
            {"goal_completion_failure": {"current_dwell_s": 0.65}},
        ),
    )
    e = engine(tmp_path, taxonomy_profile="expanded-ten-v1")
    _, ctx = e._selection()
    objective = ctx["failure_objective"]
    assert objective["measured_discovered_families"] == ["goal_completion_failure"]
    assert "goal_completion_failure" not in objective["missing_supported_families"]
    assert "fall" in objective["missing_supported_families"]
    assert any(
        o["measured_types"]["primary"] == "goal_completion_failure"
        for o in objective["behavior_observations"]
    )
    a, _ = branch_point(ctx, axis="box_mass_kg")
    b, _ = branch_point(ctx, axis="floor_friction")
    a["target_family"], b["target_family"] = "goal_completion_failure", "fall"
    candidate = selected_probe(proposal(ctx, a, b), ctx, e._memory())
    assert candidate["evidence"]["target_family"] == "fall"


def test_import_observe_summary_and_resume_share_ten_type_contract(tmp_path, monkeypatch):
    import failure_client.evaluation.expanded_taxonomy as taxonomy

    monkeypatch.setattr(
        taxonomy,
        "new_observations",
        lambda *a, **kw: (
            {
                "fall": "NOT_DETECTED",
                "locomotion_stall": "NOT_DETECTED",
                "manipulation_failure": "NOT_DETECTED",
                "goal_completion_failure": "DETECTED",
            },
            {},
        ),
    )
    e = engine(tmp_path, taxonomy_profile="expanded-ten-v1")
    calls = []

    def proposer(body, **kw):
        ctx = json.loads(body["input"][0]["content"])["context"]
        calls.append(ctx)
        p, _ = branch_point(ctx, axis="corridor_width_m")
        p["value"], p["target_family"] = 1.6, "fall"
        raw = proposal(ctx, p)
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

    e.proposer = proposer
    result = e.run(live=True, max_new_attempts=1)
    assert result["fail"] == result["valid"] == 1
    metrics = result["new_only_discovery_metrics"]
    assert metrics["targets"]["family_denominator"] == 10
    assert metrics["groups"][0]["discovered_families"] == ["goal_completion_failure"]
    assert (
        e.state["attempts"][0]["episode"]["taxonomy"]["schema_version"]
        == "expanded-goal-behavior-v1"
    )
    resumed = AutonomousAFS(e.root, runner=e.runner, proposer=proposer, fingerprint_fn=fingerprint)
    _, ctx = resumed._selection()
    review = ctx["failure_objective"]["recent_hypothesis_results"][0]
    assert review["predicted_family"] == "fall"
    assert review["observed_primary_family"] == "goal_completion_failure"
    assert ctx["remaining_valid_budget"] == 1
    assert len(calls) == len(e.runner.calls) == 1
    assert "family_denominator" in resumed.report().read_text()


def test_expanded_profile_rejected_on_legacy_selection_modes():
    with pytest.raises(ValueError, match="explicit failure-branch"):
        SearchBudget(taxonomy_profile="expanded-ten-v1")
