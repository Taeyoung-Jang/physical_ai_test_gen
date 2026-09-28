"""Offline evidence/selection regression tests; no API or robot execution."""

import copy
import json

import jsonschema
import pytest

from failure_client.archive.regression_cases import build_failure_memory
from failure_client.methods.behavior_feedback import (
    choose_probe,
    feedback_context,
    proposal_request,
    repeat_candidate,
    similar_failures,
)
from failure_client.methods.search_evidence import behavior_signature, compact_evidence
from failure_client.reporting.search_diagnostics import search_diagnostics
from llm_afs.behavior import AXES, digest

from .test_behavior_memory import fixture
from .test_discovery_measures import load, rewrite_manifest, saved_run
from .test_research_campaign import reload, setup


def interval(kind, start, end, details, phase=None):
    return {
        "kind": kind,
        "start_s": float(start),
        "end_s": float(end),
        "timing": "observation_window" if kind == "action_window" else "sampled",
        "censored": False,
        "phase": phase,
        "details": details,
        "evidence": [{"artifact": "synthetic.jsonl", "sha256": "f" * 64}],
    }


def late_failure():
    intervals = []
    for i in range(10):
        intervals.extend(
            [
                interval("phase", i * 10, i * 10 + 5, {"goal_progress_m": 0.0}, "inference_wait"),
                interval(
                    "action_window",
                    i * 10,
                    i * 10 + 9,
                    {
                        "observation_version": i,
                        "action": "plan_path" if i == 6 else "move" if i == 7 else "navigate_to",
                        "execution": "accepted",
                        "tool_status": "blocked_endpoint" if i in (6, 9) else "executed",
                        "duration_s": 2.0 if i == 7 else 8.0,
                    },
                ),
                interval(
                    "phase",
                    i * 10 + 5,
                    i * 10 + 9,
                    {
                        "goal_progress_m": -0.2 if i == 6 else 0.2,
                    },
                    "move" if i == 7 else "navigate_to",
                ),
            ]
        )
    return {
        "record": {
            "status": "VALID",
            "task_outcome": "FAIL",
            "termination_reason": "BUDGET_EXHAUSTED",
            "measures": {
                "sampled_progress_m": 2.9,
                "last_sample_goal_distance_m": 3.1,
                "event_counts": {"contact_start": 2000},
            },
        },
        "behavior": {
            "components": {"states": "AVAILABLE", "actions": "AVAILABLE", "events": "AVAILABLE"},
            "intervals": intervals,
            "object_motion": {"status": "AVAILABLE", "net_xy_displacement_m": 0.0},
        },
    }


def test_all_late_actions_survive_with_refs_without_invented_action_times():
    entry = late_failure()
    original = copy.deepcopy(entry)
    result = compact_evidence(entry)
    assert entry == original
    timeline = result["action_timeline"]
    assert [a["observation_version"] for a in timeline] == list(range(10))
    assert [
        a["observation_version"] for a in timeline if a["tool_status"] == "blocked_endpoint"
    ] == [6, 9]
    assert timeline[7]["action"] == "move"
    assert all(a["evidence"] and a["timing"] == "observation_window" for a in timeline)
    details = result["intervals"]
    assert len(details) <= 12
    assert {6, 7, 9} <= {i["details"].get("observation_version") for i in details}
    assert result["evidence_selection"]["omitted_detail_count"] == 18


def test_event_quota_unknown_components_and_small_detail_limit():
    entry = late_failure()
    for kind in ("fall", "recovery", "skill_event", "contact"):
        entry["behavior"]["intervals"].append(interval(kind, 99, 99, {}))
    entry["behavior"]["intervals"].append(interval("contact", 99, 99, {"support_contact": True}))
    result = compact_evidence(entry)
    assert {"fall", "recovery", "skill_event", "contact"} <= {
        i["kind"] for i in result["intervals"]
    }
    assert not any(i["details"].get("support_contact") for i in result["intervals"])
    assert len(compact_evidence(entry, detail_limit=1)["action_timeline"]) == 10
    entry["behavior"]["components"]["actions"] = "INVALID"
    assert behavior_signature(entry)["id"] is None
    assert compact_evidence(entry)["action_timeline_status"] == "INVALID"
    with pytest.raises(ValueError):
        compact_evidence(entry, detail_limit=0)


def test_signature_ignores_foot_counts_but_keeps_tool_sequence_and_missing_data():
    a = late_failure()
    b = copy.deepcopy(a)
    b["record"]["measures"]["event_counts"]["contact_start"] = 2500
    b["behavior"]["intervals"].append(interval("contact", 99, 99, {"support_contact": True}))
    assert behavior_signature(a)["id"] == behavior_signature(b)["id"]
    b["behavior"]["intervals"][19]["details"]["tool_status"] = "path_found"
    assert behavior_signature(a)["id"] != behavior_signature(b)["id"]
    b = copy.deepcopy(a)
    b["behavior"]["object_motion"] = {"status": "UNAVAILABLE"}
    assert behavior_signature(a)["id"] != behavior_signature(b)["id"]
    b = copy.deepcopy(a)
    b["record"]["status"] = "INCONCLUSIVE"
    assert behavior_signature(b)["id"] is None


def raw_proposal(ctx, spaces):
    return {
        "context_sha256": digest(ctx),
        "spaces": [
            {
                "mode": mode,
                "axis": axis,
                "low": low,
                "high": high,
                "evidence_refs": ["case_memory"],
                "hypothesis": "Synthetic experimental question",
                "alternative": "Another explanation",
                "falsification": "Observe goal and tool outcomes",
            }
            for mode, axis, low, high in spaces
        ],
    }


def test_purpose_then_hypothesis_order_beats_farther_endpoint(tmp_path):
    memory = build_failure_memory([load(fixture(tmp_path / "fail"))])
    ctx = feedback_context(memory, history_limit=2, remaining=6)
    raw = raw_proposal(
        ctx,
        [
            ("cross_mechanism", "box_mass_kg", 9.0, 10.0),
            ("success_probe", "floor_friction", 0.7, 0.9),
            ("success_probe", "box_mass_kg", 0.2, 10.0),
        ],
    )
    candidate = choose_probe(raw, ctx, memory)
    assert candidate["strategy"] == "success_probe"
    assert candidate["space_index"] == 1
    assert candidate["parameters"]["box_mass_kg"] == 2.0
    assert candidate["selection_audit"]["state"] == "no_success_control"
    assert len(candidate["selection_audit"]["eligible"]) == 6
    assert candidate["selection_audit"]["hypothesis_id"]
    assert not candidate["boundary_confirmed"]
    request = proposal_request(ctx, "gpt-6-luna")
    assert request["model"] == "gpt-6-luna"
    assert "campaign-hypothesis-endpoint-v2" in request["instructions"]
    jsonschema.validate(raw, request["text"]["format"]["schema"])
    raw["spaces"][0]["axis"] = "robot_speed"
    with pytest.raises(ValueError):
        choose_probe(raw, ctx, memory)


def test_behavior_cooldown_and_distinct_or_repeat_probes(tmp_path):
    records = []
    for n in range(3):
        records.append(load(fixture(tmp_path / str(n), mass=2.0 + n * 0.01)))
    memory = build_failure_memory(records)
    for n, entry in enumerate(memory["episodes"].values()):
        entry["record"]["measures"]["event_counts"] = {"contact_start": 1000 + n}
    ctx = feedback_context(memory, history_limit=2, remaining=6)
    assert similar_failures(memory, ctx["latest"]["parameters"], AXES) == 3
    assert ctx["search_selection"]["mode_priority"][0] == "cross_mechanism"
    raw = raw_proposal(ctx, [("cross_mechanism", "box_mass_kg", 2.1, 2.2)])
    with pytest.raises(ValueError, match="cooled-down"):
        choose_probe(raw, ctx, memory)
    raw["spaces"].append({**raw["spaces"][0], "axis": "floor_friction", "low": 0.1, "high": 1.4})
    chosen = choose_probe(raw, ctx, memory)
    assert chosen["space_index"] == 1
    assert chosen["selection_audit"]["rejected"]
    assert repeat_candidate(memory)["stage"] == "repeat"


def test_mixed_case_is_repeated_before_boundary_slot(tmp_path):
    engine, robot, proposer = setup(tmp_path / "campaign")
    memory = build_failure_memory(
        [
            load(fixture(tmp_path / "pass", outcome="PASS", mass=2.0)),
            load(fixture(tmp_path / "fail", outcome="FAIL", mass=2.0)),
        ]
    )
    engine._memory = lambda _: memory
    engine._valid = lambda *_: 3  # after cold start and llm slot
    candidate = engine._candidate({"method": "afs", "seed": 17})
    assert candidate["strategy"] == "mixed_outcome_repeat"
    assert candidate["stage"] == "repeat"
    assert not robot.calls and not proposer.calls


def test_milestones_do_not_claim_a_boundary_after_mixed_repeat(tmp_path):
    records = [
        load(fixture(tmp_path / "a", outcome="FAIL", mass=3.0), method="afs"),
        load(fixture(tmp_path / "b", outcome="PASS", mass=1.0), method="afs"),
        load(fixture(tmp_path / "c", outcome="PASS", mass=3.0), method="afs"),
    ]
    report = search_diagnostics(build_failure_memory(records), records)
    group = report["groups"][0]
    assert group["first_observed_success"]["valid_rollouts"] == 2
    assert group["first_observed_bracket"]["valid_rollouts"] == 2
    assert group["current_observed_brackets"] == []
    assert group["mixed_cases"][0]["passes"] == group["mixed_cases"][0]["failures"] == 1
    assert group["curve"][-1]["minimum_normalized_bracket_width"] is None
    assert report["pattern_version"] == "behavior-pattern-v1"


def test_inconclusive_preserves_observed_usage_not_failure(tmp_path):
    root = saved_run(tmp_path / "interrupt", outcome="INCONCLUSIVE", reason="response_deadline")
    path = root / "decisions.jsonl"
    row = json.loads(path.read_text())
    row["provider"] = {"usage": {"input_tokens": 123, "output_tokens": 45}}
    path.write_text(json.dumps(row) + "\n")
    rewrite_manifest(root)
    record = load(root)
    assert record.status == record.task_outcome == "INCONCLUSIVE"
    assert record.observed_input_tokens == 123 and record.observed_output_tokens == 45
    assert record.calls_with_token_usage == 1 and record.measures is None
    row["provider"]["usage"]["input_tokens"] = -1
    path.write_text(json.dumps(row) + "\n")
    rewrite_manifest(root)
    record = load(root)
    assert record.status == "INCONCLUSIVE"
    assert record.observed_input_tokens is None


def test_report_contains_diagnostics_and_resume_keeps_v2_choice(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=6)
    engine = reload(engine, robot, proposer)
    engine.run()
    path = engine.report(with_memory=True)
    metrics = json.loads((path.parent / "metrics.json").read_text())
    assert metrics["search_diagnostics"]["schema_version"] == "afs-search-diagnostics-v1"
    assert "AFS 탐색 진척" in path.read_text()
    reviews = metrics["search_diagnostics"]["experiment_reviews"]
    assert reviews and reviews[0]["execution_status"] == "VALID"
    assert reviews[0]["anchor_evidence_id"]
    assert reviews[0]["causal_assessment"] == "NOT_AUTOMATICALLY_ADJUDICATED"
    assert all(
        p["context"]["search_selection"]["policy"] == "hypothesis-v2"
        for p in engine.state["proposals"]
    )
