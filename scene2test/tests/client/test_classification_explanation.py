"""Display-only diagnostic counts and saved request inspection; no inference."""

import copy
import json
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest

from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.reporting.classification_explanation import (
    classification_explanation,
    saved_feedback_audit,
)
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from llm_afs.behavior import digest

from .test_discovery_measures import attribution, episode

RULES = {"collision": "tested-v1", "goal_occupied": "tested-v1"}


def taxonomy(**changes):
    return {
        "families": {
            f: {"status": changes.get(f, "NOT_DETECTED"), "rule_version": rule}
            for f, rule in RULES.items()
        },
        "warnings": [],
    }


def test_seven_primary_four_unmatched_one_ambiguous_without_metric_changes():
    records = [
        episode(i, attribution=attribution("collision"), taxonomy=taxonomy()) for i in range(7)
    ]
    records += [episode(i, taxonomy=taxonomy()) for i in range(7, 11)]
    records += [episode(11, taxonomy=taxonomy(collision="DETECTED", goal_occupied="DETECTED"))]
    records += [episode(12, outcome="PASS", taxonomy=taxonomy())]
    original = copy.deepcopy(records)
    before = calculate_discovery_metrics(records, family_rules=RULES)
    result = classification_explanation(records, family_rules=RULES)
    pooled = result["pooled_by_method"]["afs"]
    assert pooled["valid_fail_episodes"] == 12
    assert pooled["counts"] == {
        "primary_attributed": 7,
        "multiple_detected_no_primary": 1,
        "no_supported_rule_detected": 4,
        "measurement_unknown": 0,
        "unverified_attribution": 0,
        "unassigned_other": 0,
    }
    assert pooled["episodes"][-1]["detected_families"] == ["collision", "goal_occupied"]
    assert records == original
    assert calculate_discovery_metrics(records, family_rules=RULES) == before
    assert before["pooled_by_method"]["afs"]["unclassified_failures"] == 5


def test_unknown_untrusted_and_single_detection_are_not_misreported_as_no_detection():
    a = episode(0, taxonomy=taxonomy(collision="UNKNOWN"))
    b = episode(1, attribution=attribution("collision"), taxonomy=taxonomy())
    b.attribution.rule_version = "unreviewed-version"
    c = episode(2, taxonomy=taxonomy(collision="DETECTED"))
    result = classification_explanation([a, b, c], family_rules=RULES)
    counts = result["pooled_by_method"]["afs"]["counts"]
    assert counts["measurement_unknown"] == counts["unverified_attribution"] == 1
    assert counts["unassigned_other"] == 1 and counts["no_supported_rule_detected"] == 0


def test_missing_telemetry_and_exclusions_are_not_negative_findings():
    a = episode(0)
    excluded = a.model_copy(
        update={
            "status": "INCONCLUSIVE",
            "evidence_id": "excluded",
            "source": a.source.model_copy(update={"path": "/synthetic/excluded"}),
        }
    )
    result = classification_explanation([a, excluded], family_rules=RULES)
    assert result["pooled_by_method"]["afs"]["valid_fail_episodes"] == 1
    assert result["pooled_by_method"]["afs"]["counts"]["measurement_unknown"] == 1
    assert classification_explanation([], family_rules=RULES)["pooled_by_method"] == {}


def test_duplicates_removed_but_repeats_and_seeds_keep_episode_scope():
    a = episode(0, taxonomy=taxonomy())
    b = episode(1, scene=a.scene_id, taxonomy=taxonomy())
    c = episode(2, seed=1, taxonomy=taxonomy())
    result = classification_explanation([a, a, b, c], family_rules=RULES)
    assert result["pooled_by_method"]["afs"]["valid_fail_episodes"] == 3
    assert len(result["groups"]) == 2
    assert "not distinct-scene" in result["unit"]


def saved():
    context = {
        "failure_objective": {
            "feedback_policy": "cause-review-v3",
            "cause_review_contract": {"required": True},
            "behavior_observations": [
                {
                    "evidence_id": "observed",
                    "action_diagnostics": {"blocked_navigation_count": 3},
                    "sampled_behavior": {"progress": 1},
                }
            ],
            "trajectory_feedback": {
                "presented_episode_summaries": [
                    {"evidence_id": "observed", "patterns": {"no_manipulation_request": True}}
                ]
            },
        }
    }
    body = {
        "input": [{"content": json.dumps({"context": context, "context_sha256": digest(context)})}]
    }
    response = {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "context_sha256": digest(context),
                                "episode_reviews": [{"evidence_id": "observed"}],
                                "spaces": [{"target_family": "goal_occupied"}],
                            }
                        ),
                    }
                ]
            }
        ]
    }
    return context, body, response


def test_saved_audit_checks_actual_bound_context_and_reports_existing_information():
    ctx, body, response = saved()
    before = copy.deepcopy((ctx, body, response))
    audit = saved_feedback_audit(ctx, body, response)
    assert audit["status"] == "VERIFIED_SAVED_REQUEST_CONTEXT"
    assert audit["observations"][0]["blocked_navigation_count"] == 3
    assert audit["cause_review_contract_supplied"]
    assert audit["trajectory_summaries"][0]["patterns"]["no_manipulation_request"]
    assert audit["reviewed_evidence_ids"] == ["observed"]
    assert audit["candidate_targets"] == ["goal_occupied"]
    assert (ctx, body, response) == before
    assert "not proof" in audit["claim"]


@pytest.mark.parametrize("side", ["request", "response"])
def test_audit_rejects_context_mismatch(side):
    ctx, body, response = saved()
    if side == "request":
        body["input"][0]["content"] = json.dumps({"context": {}, "context_sha256": digest({})})
    else:
        response["output"][0]["content"][0]["text"] = json.dumps({"context_sha256": "wrong"})
    with pytest.raises(ValueError, match="mismatch"):
        saved_feedback_audit(ctx, body, response)


def test_partial_saved_response_and_unknown_layout_do_not_imply_missing_feedback():
    ctx, body, _ = saved()
    assert saved_feedback_audit(ctx, body)["response_status"] == "NOT_AVAILABLE"
    assert (
        saved_feedback_audit(ctx, body, {"output": []})["response_status"]
        == "STRUCTURED_TEXT_UNAVAILABLE"
    )
    assert (
        saved_feedback_audit(ctx, {"input": [{"content": []}]})["status"]
        == "UNSUPPORTED_REQUEST_LAYOUT"
    )


def test_cli_console_uses_saved_report_snapshot_without_second_trace_pass(tmp_path, capsys):
    main = runpy.run_path(str(Path(__file__).parents[2] / "tools/run_paired_discovery.py"))["main"]
    result = {
        "campaign": str(tmp_path),
        "purpose": "random-environment-sweep",
        "status": "COMPLETE",
        "evaluation_complete": True,
        "new_attempts": 0,
        "afs_requests_attempted": 0,
        "robot_api_call_upper_bound": 120,
        "afs_request_upper_bound": 0,
        "arms": [],
        "comparison": {},
        "smoke_is_not_target_achievement": False,
        "metrics": {"system_twelve": {"pooled_by_method": {}}},
        "classification_explanations": {"system_twelve": {"pooled_by_method": {}}},
    }
    atomic_json(tmp_path / "summary.json", result)

    def forbidden():
        pytest.fail("CLI unnecessarily reparsed traces after report snapshot")

    main.__globals__["PairedDiscovery"] = lambda *a, **k: SimpleNamespace(
        report=lambda: tmp_path / "report.html", summary=forbidden
    )
    assert main(["report", "--campaign", str(tmp_path)]) == 0
    assert '"status": "COMPLETE"' in capsys.readouterr().out
