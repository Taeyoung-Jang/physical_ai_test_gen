"""Synthetic accounting/association checks, not real robot performance evidence."""

import json

import pytest

from failure_client.evaluation.failure_taxonomy import RULES, classify_record
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics

from .test_behavior_memory import _rebind
from .test_corridor_campaign import archive
from .test_discovery_measures import json_write, load, rewrite_manifest, saved_run


def lines(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def usage(input=11, output=4, rid="resp_test"):
    return {
        "usage": {"input_tokens": input, "output_tokens": output, "total_tokens": input + output},
        "response_id": rid,
    }


def test_pending_and_journal_usage_counted_once(tmp_path):
    root = saved_run(tmp_path / "run")
    result = json.loads((root / "result.json").read_text())
    result["api_calls_attempted"] = 2
    json_write(root / "result.json", result)
    decisions = [json.loads(s) for s in (root / "decisions.jsonl").read_text().splitlines()]
    decisions[0].update(observation_version=0, provider=usage())
    lines(root / "decisions.jsonl", decisions)
    json_write(
        root / "pending_call.json",
        {"observation_version": 1, "executed": False, "provider": usage(7, 2, "resp_pending")},
    )
    for cid, meta in enumerate([usage(), usage(7, 2, "resp_pending")]):
        lines(
            root / f"api_call_{cid:03d}.jsonl",
            [
                {"observation_version": cid, "event": event, "diagnostic": meta}
                for event in ["api_completed", "policy_completed"]
            ],
        )
    rewrite_manifest(root)
    record = load(root)
    assert record.status == "VALID"
    assert (
        record.observed_input_tokens,
        record.observed_output_tokens,
        record.calls_with_token_usage,
    ) == (18, 6, 2)
    assert record.usage_audit["calls_missing_usage"] == 0


@pytest.mark.parametrize("kind", ["conflict", "shared_response", "bad_total", "negative"])
def test_conflicting_usage_excluded_without_changing_goal(tmp_path, kind):
    root = saved_run(tmp_path / "run", outcome="PASS")
    rows = [json.loads(s) for s in (root / "decisions.jsonl").read_text().splitlines()]
    rows[0].update(observation_version=0, provider=usage())
    lines(root / "decisions.jsonl", rows)
    meta, cid = usage(), 0
    if kind == "conflict":
        meta = usage(20)
    elif kind == "shared_response":
        cid = 1
    elif kind == "bad_total":
        meta["usage"]["total_tokens"] = 99
    else:
        meta["usage"]["input_tokens"] = -1
    json_write(root / "pending_call.json", {"observation_version": cid, "provider": meta})
    rewrite_manifest(root)
    record = load(root)
    assert record.task_outcome == "PASS"
    assert record.observed_input_tokens is None
    assert record.usage_audit["conflicting_call_ids"]


def dense_archive(root, *, outcome="FAIL", collision=False, occupied=False, blocked=False):
    archive(root, outcome=outcome)
    sample = json.loads((root / "states.jsonl").read_text().splitlines()[0])
    states = []
    for step in range(41):
        row = json.loads(json.dumps(sample))
        row.update(time_s=step / 5, phase="navigate_to", goal_dwell_s=0.0)
        row["qpos"][:2] = [7, 0] if outcome == "PASS" else [3.0, 0]
        row["qpos"][7:10] = [7 if occupied else 4, 0, 0.35]
        row["goal_distance_m"] = 0.0 if outcome == "PASS" else 4.0
        if outcome == "PASS" and step == 40:
            row["goal_dwell_s"] = 1.0
        states.append(row)
    lines(root / "states.jsonl", states)
    contact = {
        "robot_geom": 10,
        "world_geom": 11,
        "robot_body": "right_hand",
        "world_geom_name": "wall_north",
        "legacy_allowed": False,
    }
    lines(
        root / "events.jsonl",
        [
            {"event": "contact_start", "time_s": 6.0, "phase": "navigate_to", **contact},
            {
                "event": "contact_end",
                "time_s": 8.0,
                "phase": "navigate_to",
                "start_s": 6.0,
                "start_phase": "navigate_to",
                "truncated": False,
                "peak_normal_force_n": 20.0,
                "normal_impulse_ns": 10.0,
                "sampled_duration_s": 2.0,
                **contact,
            },
        ]
        if collision
        else [],
    )
    decisions = []
    for cid in range(2):
        decisions.extend(
            [
                {
                    "action": {"action": "plan_path", "target_xy_m": [7.0, 0.0]},
                    "execution": "accepted",
                    "observation_version": cid,
                    "latency_s": 1.0,
                },
                {
                    "event": "tool_result",
                    "observation_version": cid,
                    "result": {
                        "simulation_time_s": 7.0 + cid,
                        "status": "no_path" if blocked else "ok",
                    },
                },
            ]
        )
        json_write(
            root / f"observation_{cid:03d}.json",
            {"state_version": cid, "simulation_time_s": 6.0 + cid},
        )
    lines(root / "decisions.jsonl", decisions)
    # Remove stale skill transcript from this synthetic fixture only.
    (root / "skill_000.json").unlink()
    _rebind(root)
    return root


@pytest.mark.parametrize(
    "kwargs,family",
    [
        ({"collision": True}, "collision"),
        ({"occupied": True}, "goal_occupied"),
        ({"blocked": True}, None),  # box is 0.6 m away: no proximity evidence
    ],
)
def test_temporal_rules(tmp_path, kwargs, family):
    record = classify_record(load(dense_archive(tmp_path / "run", **kwargs)))
    assert record.task_outcome == "FAIL"
    assert record.taxonomy["primary_family"] == family, record.taxonomy


def test_interference_needs_repeated_tools_and_nearby_geometry(tmp_path):
    root = dense_archive(tmp_path / "run", blocked=True)
    rows = [json.loads(s) for s in (root / "states.jsonl").read_text().splitlines()]
    for row in rows:
        row["qpos"][0] = 3.1
        row["goal_distance_m"] = 3.9
    lines(root / "states.jsonl", rows)
    rewrite_manifest(root)
    record = classify_record(load(root))
    assert record.taxonomy["primary_family"] == "obstacle_interference", record.taxonomy


def test_success_and_ambiguity_are_not_counted_as_failure_families(tmp_path):
    success = classify_record(
        load(dense_archive(tmp_path / "pass", outcome="PASS", collision=True))
    )
    assert success.attribution is None and success.task_outcome == "PASS"
    assert all(success.taxonomy["families"][f]["status"] == "N/A" for f in RULES)
    ambiguous = classify_record(
        load(dense_archive(tmp_path / "fail", collision=True, occupied=True))
    )
    assert ambiguous.attribution is None
    assert "ambiguous_multiple_families" in ambiguous.taxonomy["warnings"]
    summary = calculate_discovery_metrics([ambiguous], family_rules=RULES)["groups"][0]
    assert summary["failure_diversity_coverage"] is None
    assert summary["diversity_target_observed"] is None
    assert summary["coverage_status"] == "partial_operational_rules"


def test_sparse_window_and_tampered_scene_remain_unknown(tmp_path):
    root = archive(tmp_path / "sparse", outcome="FAIL")
    record = classify_record(load(root))
    assert record.attribution is None
    assert "terminal_state_window_incomplete" in record.taxonomy["warnings"]
    root = dense_archive(tmp_path / "bad", occupied=True)
    (root / "scene.xml").write_text(
        (root / "scene.xml").read_text().replace('mass="2.0"', 'mass="3.0"')
    )
    rewrite_manifest(root)
    record = classify_record(load(root))
    assert record.taxonomy["families"]["goal_occupied"]["status"] == "UNKNOWN"


@pytest.mark.parametrize("kind", ["push", "support", "early", "unknown_geom", "censored"])
def test_contact_is_not_automatically_a_collision_failure(tmp_path, kind):
    root = dense_archive(tmp_path / "run", collision=True)
    events = [json.loads(s) for s in (root / "events.jsonl").read_text().splitlines()]
    for event in events:
        if kind == "push":
            event.update(world_geom_name="clear_box_geom", phase="push_object")
            if "start_phase" in event:
                event["start_phase"] = "push_object"
        elif kind == "support":
            event.update(world_geom_name="clear_floor", robot_body="left_ankle_roll_link")
        elif kind == "early":
            event["time_s"] -= 5
            if "start_s" in event:
                event["start_s"] -= 5
        elif kind == "unknown_geom":
            event["world_geom_name"] = "invented_obstacle"
        elif event["event"] == "contact_end":
            event["truncated"] = True
    lines(root / "events.jsonl", events)
    rewrite_manifest(root)
    record = classify_record(load(root))
    assert record.attribution is None
    assert record.taxonomy["families"]["collision"]["status"] in {"UNKNOWN", "NOT_DETECTED"}


def test_tilted_box_occupancy_unknown_and_taxonomy_in_afs_memory(tmp_path):
    root = dense_archive(tmp_path / "tilted", occupied=True)
    rows = [json.loads(s) for s in (root / "states.jsonl").read_text().splitlines()]
    for row in rows:
        row["qpos"][10:14] = [0.70710678, 0.70710678, 0, 0]
    lines(root / "states.jsonl", rows)
    rewrite_manifest(root)
    assert classify_record(load(root)).taxonomy["families"]["goal_occupied"]["status"] == "UNKNOWN"
    from failure_client.archive.regression_cases import build_failure_memory
    from failure_client.methods.search_evidence import compact_evidence

    record = classify_record(load(dense_archive(tmp_path / "contact", collision=True)))
    memory = build_failure_memory([record])
    assert memory["cases"][0]["primary_family"] == "collision"
    evidence = compact_evidence(memory["episodes"][record.evidence_id])
    assert evidence["operational_taxonomy"]["primary_family"] == "collision"
    assert evidence["operational_taxonomy"]["causal_status"] == "UNCONFIRMED"
