"""P1 synthetic evidence tests; no real robot/model capability claims."""

import copy
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from clear_path.contracts import Fixture
from clear_path.fixture import identity, world_xml
from failure_client.archive.regression_cases import build_failure_memory, export_failure_memory
from failure_client.evaluation.behavior_measures import analyze_behavior, interval_summary
from failure_client.evaluation.goal_run_reader import EvidenceError, _hash_file
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.reporting.discovery_report import write_discovery_report
from robot_vlm.task_outcome import digest

from .test_discovery_measures import json_write, load, rewrite_manifest, saved_run


def _rebind(root):
    protocol = json.loads((root / "protocol.json").read_text())
    result = json.loads((root / "result.json").read_text())
    result["scene_revision"] = protocol["scene_revision"]
    result["robot_condition_sha256"] = digest(
        {k: v for k, v in protocol.items() if k not in {"scene_revision", "scene_config"}}
    )
    json_write(root / "result.json", result)
    rewrite_manifest(root)


def fixture(root, *, outcome="FAIL", mass=2.0, friction=0.8):
    saved_run(root, outcome=outcome)
    config = Fixture(box_mass_kg=mass, floor_friction=friction)
    protocol = json.loads((root / "protocol.json").read_text())
    protocol.update(
        scene_config=config.model_dump(),
        scene_revision=identity(config),
        http_read_timeout_s=90.0,
        push_enabled=True,
        model="synthetic-mock",
    )
    json_write(root / "protocol.json", protocol)
    result = json.loads((root / "result.json").read_text())
    result["duration_s"] = 8.0
    json_write(root / "result.json", result)
    (root / "scene.xml").write_text(world_xml(config))
    rows = []
    for i in range(9):
        x = 7.0 if outcome == "PASS" and i >= 7 else 1.0 + i / 4
        rows.append(
            {
                "time_s": float(i),
                "phase": "settle"
                if i == 0
                else "inference_wait"
                if i < 3
                else "push_object"
                if i < 6
                else "move",
                "qpos": [x, 0, 0.75, 1, 0, 0, 0, 4 + 0.1 * max(0, i - 3), 0, 0.35, 1, 0, 0, 0],
                "qvel": [0.0] * 12,
                "ctrl": [],
                "goal_distance_m": abs(7.0 - x),
                "goal_dwell_s": 1.0 if outcome == "PASS" and i == 8 else 0.0,
            }
        )
    (root / "states.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    json_write(
        root / "robot_audit.json",
        {
            "schema_version": "clear-path-robot-audit-v1",
            "baseline_nq_nv": [7, 6],
            "combined_nq_nv": [14, 12],
            "robot_joint_identity_preserved": True,
            "gait_observation_equal": True,
        },
    )
    contact = {
        "robot_geom": 10,
        "world_geom": 11,
        "robot_body": "right_hand",
        "world_geom_name": "clear_box_geom",
        "legacy_allowed": True,
    }
    events = [
        {"event": "contact_start", "time_s": 3.0, "phase": "push_object", **contact},
        {"event": "fall_start", "time_s": 4.0, "phase": "push_object"},
        {
            "event": "fall_end",
            "time_s": 4.5,
            "phase": "push_object",
            "start_s": 4.0,
            "start_phase": "push_object",
            "truncated": False,
        },
        {"event": "upright_recovered", "time_s": 4.5, "phase": "push_object"},
        {
            "event": "contact_end",
            "time_s": 5.0,
            "phase": "push_handoff",
            "start_s": 3.0,
            "start_phase": "push_object",
            "truncated": False,
            "peak_normal_force_n": 20.0,
            "normal_impulse_ns": 10.0,
            "sampled_duration_s": 2.0,
            **contact,
        },
        {
            "event": "skill_failure",
            "time_s": 5.0,
            "phase": "push_handoff",
            "skill": "push_object",
            "reason": "SKILL_RELEASE_FAILURE",
        },
    ]
    (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
    feedback = {
        "simulation_time_s": 6.0,
        "status": "failed",
        "success": False,
        "reason": "SKILL_RELEASE_FAILURE",
        "actual_box_xyz_m": [4.3, 0.0, 0.35],
    }
    decisions = [
        {"event": "call_started", "observation_version": 0},
        {
            "action": {
                "action": "push_object",
                "object_id": "clear_box_geom",
                "target_xy_m": [4.0, 1.65],
                "duration_s": 18.0,
            },
            "execution": "accepted",
            "observation_version": 0,
            "latency_s": 999.0,
            "provider": {"request_id": "synthetic-" + root.name},
        },
        {"event": "tool_result", "observation_version": 0, "result": feedback},
    ]
    (root / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in decisions))
    json_write(root / "skill_000.json", feedback)
    json_write(root / "observation_000.json", {"state_version": 0, "simulation_time_s": 2.0})
    # Binary placeholders test byte-preserving export, NOT video rendering/playability.
    (root / "rollout.mp4").write_bytes(b"synthetic-mp4-placeholder")
    (root / "rollout.gif").write_bytes(b"old-gif-must-not-be-copied")
    (root / "api_call_000.jsonl").write_text('{"authorization":"Bearer secret-not-for-export"}\n')
    _rebind(root)
    assert load(root).status == "VALID"
    return root


def test_intervals_exact_contacts_sampled_phases_and_inference_window(tmp_path):
    record = load(fixture(tmp_path / "run"))
    analysis = analyze_behavior(record)
    assert analysis.status == "AVAILABLE", analysis.warnings
    assert interval_summary(analysis) == {
        "phase_intervals": 4,
        "contact_intervals": 1,
        "fall_intervals": 1,
        "recovery_events": 1,
        "action_windows": 1,
    }
    contact = next(i for i in analysis.intervals if i.kind == "contact")
    assert (contact.start_s, contact.end_s, contact.censored) == (3.0, 5.0, False)
    assert contact.details["normal_impulse_ns"] == 10.0
    assert contact.evidence[0].first_line == 1 and contact.evidence[1].first_line == 5
    window = next(i for i in analysis.intervals if i.kind == "action_window")
    assert (window.start_s, window.end_s) == (2.0, 6.0)
    assert window.details["inference_wall_s"] == 999.0
    assert window.details["execution_start_s"] is None
    assert window.details["tool_success"] is False
    assert analysis.object_motion["net_xy_displacement_m"] == pytest.approx(0.5)
    assert analysis.max_state_sample_gap_s == 1.0
    assert record.task_outcome == "FAIL" and record.attribution is None


def test_events_do_not_turn_a_goal_pass_into_failure(tmp_path):
    record = load(fixture(tmp_path / "pass", outcome="PASS"))
    memory = build_failure_memory([record])
    case = memory["cases"][0]
    assert (case["pass_count"], case["fail_count"], case["role"]) == (1, 0, "success_control")
    assert case["primary_family"] is None and case["causal_status"] == "UNKNOWN"
    assert calculate_discovery_metrics([record])["groups"][0]["failure_discovery_rate"] == 0


@pytest.mark.parametrize("missing", ["start", "end"])
def test_missing_contact_endpoint_is_censored_not_invented(tmp_path, missing):
    root = fixture(tmp_path / "run")
    events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()]
    events = [r for r in events if r["event"] != "contact_" + missing]
    (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
    rewrite_manifest(root)
    report = analyze_behavior(load(root))
    contact = next(i for i in report.intervals if i.kind == "contact")
    assert contact.censored
    assert report.status == "PARTIAL"
    if missing == "end":
        assert contact.end_s is None and "normal_impulse_ns" not in contact.details


@pytest.mark.parametrize("fault", ["mismatch", "negative", "after_end", "duplicate", "reverse"])
def test_invalid_event_component_is_not_a_robot_failure(tmp_path, fault):
    root = fixture(tmp_path / "run", outcome="PASS")
    events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()]
    if fault == "mismatch":
        events[4]["start_s"] = 2.5
    elif fault == "negative":
        events[4]["normal_impulse_ns"] = -1
    elif fault == "after_end":
        events[-1]["time_s"] = 99
    elif fault == "duplicate":
        events.insert(1, events[0])
    else:
        events.reverse()
    (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
    rewrite_manifest(root)
    record = load(root)
    report = analyze_behavior(record)
    assert record.task_outcome == "PASS"
    assert report.status == "PARTIAL" and report.components["events"] == "INVALID"
    assert interval_summary(report)["contact_intervals"] is None


def test_missing_telemetry_is_unknown_and_box_address_is_not_guessed(tmp_path):
    root = fixture(tmp_path / "run")
    (root / "events.jsonl").unlink()
    (root / "robot_audit.json").unlink()
    rewrite_manifest(root)
    report = analyze_behavior(load(root))
    assert report.components["events"] == "UNAVAILABLE"
    assert report.object_motion["status"] == "UNSUPPORTED"
    assert interval_summary(report)["contact_intervals"] is None


def test_no_observation_timestamp_remains_unknown(tmp_path):
    root = fixture(tmp_path / "run")
    (root / "observation_000.json").unlink()
    rewrite_manifest(root)
    report = analyze_behavior(load(root))
    window = next(i for i in report.intervals if i.kind == "action_window")
    assert window.start_s is None and window.end_s == 6.0 and window.censored
    assert window.timing == "unknown" and report.status == "PARTIAL"


def test_skill_file_disagreement_marks_only_actions_invalid(tmp_path):
    root = fixture(tmp_path / "run")
    skill = json.loads((root / "skill_000.json").read_text())
    skill["success"] = True
    json_write(root / "skill_000.json", skill)
    rewrite_manifest(root)
    report = analyze_behavior(load(root))
    assert report.components["actions"] == "INVALID"
    assert "actions:skill_result_mismatch" in report.warnings


def test_source_change_after_import_is_rejected(tmp_path):
    root = fixture(tmp_path / "run")
    record = load(root)
    (root / "events.jsonl").write_text("")
    with pytest.raises(EvidenceError):
        analyze_behavior(record)
    rewrite_manifest(root)
    with pytest.raises(EvidenceError, match="source_changed"):
        analyze_behavior(record)


def test_mixed_repeats_and_copy_deduplication(tmp_path):
    a = fixture(tmp_path / "a", outcome="PASS")
    b = fixture(tmp_path / "b", outcome="FAIL")
    shutil.copytree(a, tmp_path / "copy")
    memory = build_failure_memory([load(a), load(b), load(tmp_path / "copy")])
    assert len(memory["duplicates"]) == 1 and len(memory["cases"]) == 1
    case = memory["cases"][0]
    assert case["role"] == "mixed_outcomes" and case["empirical_failure_rate"] == 0.5
    assert len(case["episodes"]) == 2 and memory["brackets"] == []


def test_single_axis_bracket_carries_endpoint_counts_without_monotonic_claim(tmp_path):
    a = fixture(tmp_path / "pass", mass=1.0, outcome="PASS")
    b = fixture(tmp_path / "fail", mass=3.0)
    memory = build_failure_memory([load(a), load(b)])
    assert len(memory["brackets"]) == 1
    bracket = memory["brackets"][0]
    assert bracket["axis"] == "box_mass_kg"
    assert bracket["midpoint_probe"] == 2.0 and bracket["low"]["passes"] == 1
    assert bracket["normalized_width"] == pytest.approx(2.0 / 9.8)
    assert "no monotonicity" in bracket["limits"]


@pytest.mark.parametrize("change", ["robot", "two_axes", "geometry", "mixed", "all_fail"])
def test_noncomparable_or_mixed_outcomes_do_not_make_a_boundary(tmp_path, change):
    a = fixture(tmp_path / "a", mass=1.0, outcome="FAIL" if change == "all_fail" else "PASS")
    b = fixture(tmp_path / "b", mass=3.0, friction=0.5 if change == "two_axes" else 0.8)
    roots = [a, b]
    if change == "robot":
        proto = json.loads((b / "protocol.json").read_text())
        proto["model"] = "different-mock"
        json_write(b / "protocol.json", proto)
        _rebind(b)
    elif change == "geometry":
        xml = (b / "scene.xml").read_text().replace('name="wall_east"', 'name="changed_wall"')
        (b / "scene.xml").write_text(xml)
        rewrite_manifest(b)
    elif change == "mixed":
        roots.append(fixture(tmp_path / "mixed", mass=1.0))
    memory = build_failure_memory([load(r) for r in roots])
    assert memory["brackets"] == []
    if change == "geometry":
        assert any(c["parameters"] is None for c in memory["cases"])


def test_legacy_and_incomplete_records_are_not_promoted_to_memory(tmp_path):
    root = saved_run(tmp_path / "old", legacy=True)
    memory = build_failure_memory([load(root), load(tmp_path / "missing")])
    assert memory["cases"] == [] and len(memory["excluded"]) == 2
    report = export_failure_memory(tmp_path / "export", memory)
    assert "missing_manifest" in report.read_text()


@pytest.mark.parametrize("include_video", [False, True])
def test_export_is_checksummed_nonoverwriting_and_never_copies_gif_or_api(tmp_path, include_video):
    root = fixture(tmp_path / "run")
    before = {p.name: p.read_bytes() for p in root.iterdir()}
    memory = build_failure_memory([load(root)])
    target = tmp_path / "export"
    export_failure_memory(target, memory, include_video=include_video)
    eid = next(iter(memory["episodes"]))
    evidence = target / "evidence" / eid
    assert (evidence / "rollout.mp4").exists() is include_video
    assert not (evidence / "rollout.gif").exists()
    assert not (evidence / "api_call_000.jsonl").exists()
    assert "#t=" in (evidence / "index.html").read_text()
    assert "includes_inference_wait" in (evidence / "behavior.json").read_text()
    cid = memory["cases"][0]["case_id"]
    command = (target / "cases" / cid / "REPRODUCE.txt").read_text()
    assert "--enable-push" in command and "--max-seconds" not in command
    manifest = json.loads((target / "manifest.json").read_text())
    assert not manifest["standalone_robot_environment"]
    for entry in manifest["artifacts"]:
        assert _hash_file(target / entry["path"]) == entry["sha256"]
    assert {p.name: p.read_bytes() for p in root.iterdir()} == before
    with pytest.raises(FileExistsError):
        export_failure_memory(target, memory)
    with pytest.raises(ValueError, match="source run"):
        export_failure_memory(root / "forbidden", memory)


def test_credentials_in_selected_evidence_are_rejected_before_copy(tmp_path):
    root = fixture(tmp_path / "run")
    obs = json.loads((root / "observation_000.json").read_text())
    obs["authorization"] = "sensitive"
    json_write(root / "observation_000.json", obs)
    rewrite_manifest(root)
    memory = build_failure_memory([load(root)])
    target = tmp_path / "export"
    with pytest.raises(ValueError, match="credential-like"):
        export_failure_memory(target, memory)
    assert not target.exists()


def test_export_rechecks_files_after_analysis(tmp_path):
    root = fixture(tmp_path / "run")
    memory = build_failure_memory([load(root)])
    (root / "scene.xml").write_text("changed")
    with pytest.raises(ValueError, match="source_changed"):
        export_failure_memory(tmp_path / "export", memory)


def test_report_with_memory_links_nested_manifest(tmp_path):
    record = load(fixture(tmp_path / "run"))
    memory = build_failure_memory([record])
    output = tmp_path / "report"
    page = write_discovery_report(
        output, "synthetic", [record], calculate_discovery_metrics([record]), memory=memory
    )
    assert "memory/index.html" in page.read_text()
    entries = json.loads((output / "manifest.json").read_text())["artifacts"]
    assert any(e["path"] == "memory/index.html" for e in entries)
    assert any(e["path"] == "memory/manifest.json" for e in entries)


def test_xss_in_event_reason_is_escaped(tmp_path):
    root = fixture(tmp_path / "run")
    path = root / "events.jsonl"
    path.write_text(path.read_text().replace("SKILL_RELEASE_FAILURE", "<script>alert(1)</script>"))
    rewrite_manifest(root)
    memory = build_failure_memory([load(root)])
    export_failure_memory(tmp_path / "out", memory)
    eid = next(iter(memory["episodes"]))
    html = (tmp_path / "out/evidence" / eid / "index.html").read_text()
    assert "<script>alert" not in html and "&lt;script&gt;" in html


def test_cli_with_memory_and_empty_exclusions(tmp_path):
    root = fixture(tmp_path / "run")
    tool = Path(__file__).resolve().parents[2] / "tools/measure_failure_discovery.py"
    result = subprocess.run(
        [
            sys.executable,
            str(tool),
            "--run",
            str(root),
            "--with-memory",
            "--output-dir",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "cases=1; brackets=0" in result.stdout
    assert (tmp_path / "out/memory/index.html").exists()


def test_bundle_video_requires_memory_flag(tmp_path):
    tool = Path(__file__).resolve().parents[2] / "tools/measure_failure_discovery.py"
    result = subprocess.run(
        [sys.executable, str(tool), "--run", str(tmp_path / "none"), "--bundle-video"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2 and "requires --with-memory" in result.stderr


def test_memory_rejects_malicious_output_ids(tmp_path):
    memory = build_failure_memory([load(fixture(tmp_path / "run"))])
    bad = copy.deepcopy(memory)
    bad["cases"][0]["case_id"] = "../escape"
    with pytest.raises(ValueError, match="unsafe case ID"):
        export_failure_memory(tmp_path / "out", bad)


def test_bad_box_address_does_not_erase_independent_phase_metrics(tmp_path):
    root = fixture(tmp_path / "run")
    audit = json.loads((root / "robot_audit.json").read_text())
    audit["baseline_nq_nv"] = [8, 7]
    audit["combined_nq_nv"] = [15, 13]
    json_write(root / "robot_audit.json", audit)
    rewrite_manifest(root)
    report = analyze_behavior(load(root))
    assert report.components["states"] == "AVAILABLE"
    assert report.object_motion == {"status": "UNSUPPORTED", "reason": "box_state_length_mismatch"}
    assert interval_summary(report)["phase_intervals"] == 4


def test_video_bundle_remains_linked_after_move_without_original(tmp_path):
    root = fixture(tmp_path / "run")
    memory = build_failure_memory([load(root)])
    export_failure_memory(tmp_path / "bundle", memory, include_video=True)
    (tmp_path / "bundle").rename(tmp_path / "moved")
    root.rename(tmp_path / "source_no_longer_at_old_path")
    eid = next(iter(memory["episodes"]))
    folder = tmp_path / "moved/evidence" / eid
    assert 'src="rollout.mp4"' in (folder / "index.html").read_text()
    assert (folder / "rollout.mp4").read_bytes() == b"synthetic-mp4-placeholder"


def test_truncated_contact_is_not_reported_as_a_finished_episode(tmp_path):
    root = fixture(tmp_path / "run")
    events = [json.loads(x) for x in (root / "events.jsonl").read_text().splitlines()]
    events[4]["truncated"] = True
    (root / "events.jsonl").write_text("".join(json.dumps(r) + "\n" for r in events))
    rewrite_manifest(root)
    contact = next(i for i in analyze_behavior(load(root)).intervals if i.kind == "contact")
    assert contact.censored is True


def test_failed_copy_never_commits_unverified_bytes(tmp_path):
    from failure_client.archive.regression_cases import _copy_checked

    source, dest = tmp_path / "source", tmp_path / "dest"
    source.write_bytes(b"changed-after-preflight")
    with pytest.raises(ValueError, match="source_changed"):
        _copy_checked(source, dest, "0" * 64)
    assert not dest.exists() and not list(tmp_path.glob(".copy-*"))
