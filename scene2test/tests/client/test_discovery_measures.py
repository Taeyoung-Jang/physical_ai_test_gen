"""Offline synthetic measurements only: no API, GPU or success-rate evidence."""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import (
    FAMILIES,
    Attribution,
    ComparisonDesign,
    EpisodeRecord,
    RunInput,
)
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics as calculate
from failure_client.reporting.discovery_report import write_discovery_report
from robot_vlm.task_outcome import GoalEvaluator, digest, task_contract


def episode(index, *, method="afs", seed=0, outcome="FAIL", scene=None, **extra):
    identity = f"{method}-{seed}-{index}"
    return EpisodeRecord(
        source=RunInput(path=f"/synthetic/{identity}", method=method, seed=seed),
        evidence_id=identity,
        status="VALID",
        task_outcome=outcome,
        condition_id="same",
        scene_id=scene or identity,
        policy_origin="mock",
        artifact_hashes={"events.jsonl": "hash"},
        **extra,
    )


def design(budget, seeds=None, **changes):
    return ComparisonDesign(
        domain_id="three-axes-v1",
        sampling_distribution="uniform",
        condition_id="same",
        valid_budget_per_seed=budget,
        seeds=[0] if seeds is None else seeds,
        **changes,
    )


def rewrite_manifest(root):
    entries = [
        {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted(root.iterdir())
        if p.name != "manifest.json"
    ]
    (root / "manifest.json").write_text(json.dumps({"artifacts": entries}))


def json_write(path, value):
    path.write_text(json.dumps(value, allow_nan=False))


def saved_run(root, *, outcome="FAIL", legacy=False, reason=None):
    root.mkdir()
    profile = "legacy_guarded" if legacy else "goal_outcome_v1"
    contract = task_contract([7.0, 0.0], 10, None, profile)
    protocol = {
        "schema_version": "robot-goal-agent-v5",
        "evaluation_profile": profile,
        "task_contract": contract,
        "task_contract_sha256": digest(contract),
        "max_calls": 10,
        "max_simulation_s": None,
        "policy_origin": "mock",
        "source_hashes": {"runner": "f" * 64},
        "robot_resources": {"robot.xml": "f" * 64},
        "scene_revision": "scene-v1",
        "scene_config": {"box_mass_kg": 2.0},
    }
    condition = {k: v for k, v in protocol.items() if k not in {"scene_revision", "scene_config"}}
    reason = reason or ("GOAL_REACHED" if outcome == "PASS" else "BUDGET_EXHAUSTED")
    evaluator = GoalEvaluator(contract)
    evaluator.goal_reached = outcome == "PASS"
    result = {
        **evaluator.result(reason, outcome != "INCONCLUSIVE"),
        "robot_condition_sha256": digest(condition),
        "scene_revision": "scene-v1",
        "duration_s": 2.0,
        "api_calls_attempted": 0,
        "reason": reason,
        "policy_origin": "mock",
    }
    json_write(root / "protocol.json", protocol)
    json_write(root / "result.json", result)
    (root / "scene.xml").write_text("<mujoco/>")
    rows = [
        {
            "time_s": float(i),
            "qpos": [float(i + 1), 0, 0.75, 1, 0, 0, 0],
            "qvel": [0.0],
            "ctrl": [0.0],
            "goal_distance_m": float(6 - i),
            "goal_dwell_s": 0.0,
        }
        for i in range(3)
    ]
    if outcome == "PASS":
        for i in (1, 2):
            rows[i]["qpos"][0] = 7.0
            rows[i]["goal_distance_m"] = 0.0
            rows[i]["goal_dwell_s"] = float(i - 1)
    (root / "states.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (root / "decisions.jsonl").write_text(
        json.dumps(
            {
                "action": {"action": "move"},
                "execution": "accepted",
                "observation_version": 0,
            }
        )
        + "\n"
    )
    (root / "events.jsonl").write_text('{"event":"contact_started"}\n')
    rewrite_manifest(root)
    return root


def load(root, **kwargs):
    return read_goal_run(RunInput(path=str(root), **kwargs))


def test_exact_blueprint_example_and_curves():
    records = [
        episode(i, method=method, outcome="FAIL" if i < failures else "PASS")
        for method, failures in [("afs", 30), ("random", 25)]
        for i in range(100)
    ]
    result = calculate(records, design(100))
    assert result["comparison"]["relative_gain"] == 0.20
    assert result["comparison"]["difference_percentage_points"] == 5.0
    assert result["comparison"]["gain_target_observed"] is True
    afs = result["pooled_by_method"]["afs"]
    assert afs["failure_discovery_rate"] == 0.30
    assert afs["fdr_target_observed"] is True
    assert afs["curve_input_order"][-1]["failures"] == 30
    assert afs["failure_diversity_coverage"] is None
    assert set(afs["family_status"].values()) == {"UNSUPPORTED"}


@pytest.mark.parametrize(
    "a,r,gain,status",
    [
        (0, 0, None, "baseline_zero"),
        (2, 0, None, "baseline_zero"),
        (0, 2, -1.0, "measured"),
        (2, 2, 0.0, "measured"),
    ],
)
def test_zero_baseline_and_negative_gain(a, r, gain, status):
    records = [
        episode(i, method=m, outcome="FAIL" if i < f else "PASS")
        for m, f in [("afs", a), ("random", r)]
        for i in range(2)
    ]
    comparison = calculate(records, design(2))["comparison"]
    assert comparison["relative_gain"] == gain
    assert comparison["status"] == status
    if gain is None:
        assert comparison["gain_target_observed"] is None


def test_no_valid_data_is_not_zero_rate():
    metrics = calculate([], design(10))
    assert metrics["comparison"]["status"] == "not_comparable"
    assert all(g["failure_discovery_rate"] is None for g in metrics["groups"])
    assert all(g["budget_status"] == "incomplete" for g in metrics["groups"])


def test_duplicate_copy_and_independent_repeat_count():
    a = episode(0, scene="same-scene")
    copied = a.model_copy(update={"source": a.source.model_copy(update={"path": "/copied"})})
    repeat = episode(1, scene="same-scene")
    repeat.source.stage = "repeat"
    summary = calculate([a, copied, repeat])
    assert len(summary["duplicate_records"]) == 1
    g = summary["groups"][0]
    assert (g["valid_rollouts"], g["unique_failure_scenes"], g["repeated_scene_failures"]) == (
        2,
        1,
        1,
    )
    assert g["valid_stage_counts"] == {"unknown": 1, "repeat": 1}


@pytest.mark.parametrize("field,value", [("task_outcome", "PASS"), ("condition_id", "other")])
def test_conflicting_copies_are_not_silently_deduplicated(field, value):
    a = episode(0)
    with pytest.raises(ValueError, match="conflicting"):
        calculate([a, a.model_copy(update={field: value})])


def test_cannot_use_same_rollout_for_both_methods():
    a = episode(0)
    other = a.model_copy(update={"source": a.source.model_copy(update={"method": "random"})})
    with pytest.raises(ValueError, match="assignment"):
        calculate([a, other])


@pytest.mark.parametrize("change", ["condition", "seed", "under", "over", "unassigned"])
def test_comparison_requires_matching_conditions_seeds_and_budget(change):
    records = [episode(0), episode(0, method="random")]
    if change == "condition":
        records[1].condition_id = "other"
    elif change == "seed":
        records[1].source.seed = 9
    elif change == "under":
        records.pop()
    elif change == "over":
        records.append(episode(1))
    else:
        records[0].source.method = "unassigned"
    comparison = calculate(records, design(1))["comparison"]
    assert comparison["status"] == "not_comparable"
    assert comparison["relative_gain"] is None


def test_mixed_conditions_do_not_produce_a_pooled_rate():
    a, b = episode(0), episode(1)
    b.condition_id = "different-robot"
    g = calculate([a, b])["groups"][0]
    assert not g["conditions_compatible"]
    assert g["failure_discovery_rate"] is None


def attribution(family):
    return Attribution(
        primary_family=family, rule_version="tested-v1", evidence_refs=["events.jsonl"]
    )


def test_four_evidence_backed_families_and_untrusted_labels():
    records = [episode(i, attribution=attribution(f)) for i, f in enumerate(FAMILIES[:4])]
    assert calculate(records)["groups"][0]["failure_diversity_coverage"] is None
    result = calculate(records, family_rules={f: "tested-v1" for f in FAMILIES[:4]})
    group = result["groups"][0]
    assert group["failure_diversity_coverage"] == 4 / 6
    assert group["diversity_target_observed"] is True
    assert group["family_status"]["human_safety_risk"] == "UNSUPPORTED"
    assert group["unclassified_failures"] == 0


def test_relabeling_one_scene_does_not_inflate_diversity():
    records = [
        episode(i, scene="one", attribution=attribution(f)) for i, f in enumerate(FAMILIES[:4])
    ]
    group = calculate(records, family_rules={f: "tested-v1" for f in FAMILIES})["groups"][0]
    assert group["failure_diversity_coverage"] == 0
    assert group["ambiguous_family_scenes"] == ["one"]


def test_success_events_cannot_be_counted_as_failure_types():
    with pytest.raises(ValueError, match="valid goal FAIL"):
        episode(0, outcome="PASS", attribution=attribution("collision"))
    with pytest.raises(ValueError, match="verified artifact"):
        episode(
            1,
            attribution=Attribution(
                primary_family="collision", rule_version="tested", evidence_refs=["invented"]
            ),
        )


def test_pooled_union_is_not_per_seed_coverage():
    records = [episode(i, seed=i, attribution=attribution(f)) for i, f in enumerate(FAMILIES[:4])]
    metrics = calculate(records, family_rules={f: "tested-v1" for f in FAMILIES})
    assert all(g["discovered_family_count"] == 1 for g in metrics["groups"])
    assert metrics["pooled_by_method"]["afs"]["discovered_family_count"] == 4


def test_reader_computes_passive_measures_and_does_not_label_contacts(tmp_path):
    root = saved_run(tmp_path / "run")
    record = load(root)
    assert record.status == "VALID", record.exclusion_reason
    assert record.task_outcome == "FAIL"
    assert record.measures.sampled_progress_m == 2.0
    assert record.measures.sampled_path_length_m == 2.0
    assert record.measures.initial_goal_distance_m == 6.0
    assert record.measures.event_counts == {"contact_started": 1}
    assert record.measures.maximum_base_tilt_deg == 0.0
    assert record.attribution is None
    assert record.observed_input_tokens is None


def test_contact_with_recorded_goal_success_is_pass(tmp_path):
    record = load(saved_run(tmp_path / "pass", outcome="PASS"))
    # The sparse states are not used to replay the full-rate evaluator's dwell contract.
    assert record.status == "VALID" and record.task_outcome == "PASS"
    assert record.measures.event_counts["contact_started"] == 1


def test_reader_copied_archive_has_same_evidence_id(tmp_path):
    root = saved_run(tmp_path / "original")
    shutil.copytree(root, tmp_path / "copy")
    assert load(root).evidence_id == load(tmp_path / "copy").evidence_id
    assert calculate([load(root), load(tmp_path / "copy")])["unique_records"] == 1


@pytest.mark.parametrize(
    "fault,code",
    [
        ("manifest", "missing_manifest"),
        ("missing", "missing_artifact"),
        ("hash", "artifact_hash_mismatch"),
        ("traversal", "unsafe_or_duplicate_artifact_path"),
        ("duplicate", "unsafe_or_duplicate_artifact_path"),
        ("absolute", "unsafe_or_duplicate_artifact_path"),
    ],
)
def test_incomplete_or_unsafe_artifacts_never_count_as_fail(tmp_path, fault, code):
    root = saved_run(tmp_path / "run")
    path = root / "manifest.json"
    manifest = json.loads(path.read_text())
    if fault == "manifest":
        path.unlink()
    elif fault == "missing":
        (root / "result.json").unlink()
    elif fault == "hash":
        (root / "scene.xml").write_text("changed")
    else:
        if fault == "duplicate":
            manifest["artifacts"].append(manifest["artifacts"][0])
        else:
            manifest["artifacts"][0]["path"] = (
                "../escape" if fault == "traversal" else "/tmp/escape"
            )
        json_write(path, manifest)
    record = load(root)
    assert record.exclusion_reason == code
    group = calculate([record])["groups"][0]
    assert group["valid_rollouts"] == group["failures"] == 0
    assert group["failure_discovery_rate"] is None


def test_legacy_and_api_failures_are_excluded_with_costs(tmp_path):
    legacy = load(saved_run(tmp_path / "old", legacy=True, reason="FORBIDDEN_CONTACT"))
    assert legacy.status == "UNSUPPORTED"
    api = load(saved_run(tmp_path / "api", outcome="INCONCLUSIVE", reason="response_deadline"))
    assert api.status == "INCONCLUSIVE"
    assert api.simulation_s == 2.0
    metrics = calculate([legacy, api])["groups"][0]
    assert metrics["excluded_rollouts"] == 2
    assert metrics["costs"]["simulation_s"]["observed_total"] == 2.0
    assert metrics["costs"]["simulation_s"]["records_missing"] == 1


@pytest.mark.parametrize("fault", ["condition", "goal_hash", "flag", "integer_flag", "termination"])
def test_inconsistent_result_is_rejected_even_with_new_manifest(tmp_path, fault):
    root = saved_run(tmp_path / "run")
    result = json.loads((root / "result.json").read_text())
    if fault == "condition":
        result["robot_condition_sha256"] = "wrong"
    elif fault == "goal_hash":
        result["task_contract_sha256"] = "wrong"
    elif fault == "flag":
        result["execution_valid"] = False
    elif fault == "integer_flag":
        result["goal_reached"] = 0
    else:
        result["termination"]["actor"] = "robot"
    json_write(root / "result.json", result)
    rewrite_manifest(root)
    assert load(root).status == "INVALID"


@pytest.mark.parametrize("fault", ["empty", "nan", "goal_distance", "time", "duplicate_key"])
def test_bad_trace_is_excluded(tmp_path, fault):
    root = saved_run(tmp_path / "run")
    path = root / "states.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if fault == "empty":
        path.write_text("")
    elif fault == "nan":
        rows[0]["qpos"][0] = float("nan")
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    elif fault == "duplicate_key":
        path.write_text('{"time_s":0,"time_s":1}\n')
    else:
        rows[1]["goal_distance_m" if fault == "goal_distance" else "time_s"] = 0
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    rewrite_manifest(root)
    assert load(root).status == "INVALID"


def test_unknown_event_stream_and_partial_token_usage(tmp_path):
    root = saved_run(tmp_path / "run")
    (root / "events.jsonl").unlink()
    decision = json.loads((root / "decisions.jsonl").read_text())
    decision["provider"] = {
        "model": "test-model",
        "usage": {"input_tokens": 11, "output_tokens": 4},
    }
    (root / "decisions.jsonl").write_text(json.dumps(decision) + "\n")
    rewrite_manifest(root)
    record = load(root)
    assert record.measures.event_counts is None
    assert record.observed_input_tokens == 11 and record.calls_with_token_usage == 1


def test_report_is_nonoverwriting_and_html_escaped(tmp_path):
    root = saved_run(tmp_path / "run")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    records = [load(root)]
    output = tmp_path / "report"
    report = write_discovery_report(output, "<script>evil</script>", records, calculate(records))
    assert "<script>evil" not in report.read_text()
    assert "&lt;script&gt;" in report.read_text()
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    assert {p.name for p in output.iterdir()} == {
        "episodes.jsonl",
        "metrics.json",
        "metrics.csv",
        "report.html",
        "manifest.json",
    }
    with pytest.raises(FileExistsError):
        write_discovery_report(output, "x", records, calculate(records))
    with pytest.raises(ValueError, match="source run"):
        write_discovery_report(root / "nested", "x", records, calculate(records))


def test_cli_runs_without_model_key_or_gpu(tmp_path):
    root = saved_run(tmp_path / "run")
    tool = Path(__file__).resolve().parents[2] / "tools/measure_failure_discovery.py"
    output = tmp_path / "report"
    result = subprocess.run(
        [sys.executable, str(tool), "--run", str(root), "--output-dir", str(output)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "valid=1; excluded=0" in result.stdout
    assert "COMPARISON=missing_comparison_design" in result.stdout
    metrics = json.loads((output / "metrics.json").read_text())
    assert metrics["groups"][0]["failure_discovery_rate"] == 1.0


def test_cli_declared_design_and_relative_input_paths(tmp_path):
    first = saved_run(tmp_path / "first")
    second = saved_run(tmp_path / "second", outcome="PASS")
    condition = load(first).condition_id
    config = {
        "schema_version": "failure-measurement-input-v1",
        "campaign_id": "synthetic",
        "design": {**design(1).model_dump(), "condition_id": condition},
        "runs": [
            {"path": "first", "method": "afs", "seed": 0},
            {"path": "second", "method": "random", "seed": 0},
        ],
    }
    json_write(tmp_path / "input.json", config)
    tool = Path(__file__).resolve().parents[2] / "tools/measure_failure_discovery.py"
    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--input",
            str(tmp_path / "input.json"),
            "--output-dir",
            str(tmp_path / "output"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "COMPARISON=baseline_zero" in result.stdout
    assert load(second).condition_id == condition


def test_strict_contract_rejects_unknown_fields_and_nonfinite_values():
    with pytest.raises(ValueError):
        RunInput(path="x", family="collision")
    with pytest.raises(ValueError):
        episode(0, simulation_s=float("nan"))
    with pytest.raises(ValueError):
        ComparisonDesign(**{**design(1).model_dump(), "seeds": [0, 0]})
    bad = copy.deepcopy(episode(0))
    bad.status = "INCOMPLETE"
    with pytest.raises(ValueError):
        calculate([bad])


def test_all_exploration_stages_consume_valid_budget():
    records = [episode(i) for i in range(4)]
    for r, stage in zip(records, ["cold_start", "discovery", "repeat", "boundary"], strict=True):
        r.source.stage = stage
    g = calculate(records, design(4))["groups"][0]
    assert g["valid_rollouts"] == 4 and g["budget_status"] == "complete"
    assert sum(g["valid_stage_counts"].values()) == 4


def test_missing_live_model_identity_blocks_comparison():
    a, r = episode(0), episode(0, method="random")
    a.policy_origin = r.policy_origin = "openai_api"
    comparison = calculate([a, r], design(1))["comparison"]
    assert comparison["issues"] == ["missing_returned_model_identity"]


def test_outside_manifest_symlink_is_rejected(tmp_path):
    root = saved_run(tmp_path / "run")
    manifest = root / "manifest.json"
    outside = tmp_path / "outside.json"
    manifest.rename(outside)
    manifest.symlink_to(outside)
    assert load(root).exclusion_reason == "unsafe_manifest_path"


def test_malformed_inconclusive_reason_does_not_abort_batch(tmp_path):
    root = saved_run(tmp_path / "run", outcome="INCONCLUSIVE")
    result = json.loads((root / "result.json").read_text())
    result["reason"] = 123
    result["termination"]["reason"] = 123
    json_write(root / "result.json", result)
    rewrite_manifest(root)
    assert load(root).exclusion_reason == "invalid_termination_reason"
