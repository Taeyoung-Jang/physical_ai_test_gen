"""Offline gate explanation must not invent labels from whole-episode events."""

import copy
import runpy

import pytest

from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import RunInput

from .test_afs_contrast import source


@pytest.fixture
def tool():
    return runpy.run_path("tools/audit_failure_phases.py")


def test_valid_archive_read_only_audit_and_non_overwriting_report(tool, tmp_path):
    root = source(tmp_path / "archive", outcome="FAIL")
    before = {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    row = tool["audit_run"](root)
    assert row["task_outcome"] == "FAIL" and row["status"] == "VALID"
    assert row["existing_taxonomy"]["primary_family"] is None
    assert row["whole_episode"]["action_counts"]
    assert row["artifact_hashes"] == read_goal_run(RunInput(path=str(root))).artifact_hashes
    report = tool["write_report"](tmp_path / "report", [row])
    assert report.is_file() and (report.parent / "audit.json").is_file()
    assert before == {p.name: p.read_bytes() for p in root.iterdir() if p.is_file()}
    with pytest.raises(FileExistsError):
        tool["write_report"](report.parent, [row])
    with pytest.raises(ValueError, match="separate"):
        tool["write_report"](root / "new-report", [row])


def test_incomplete_archive_remains_excluded_with_unknown_counts(tool, tmp_path):
    root = source(tmp_path / "archive")
    (root / "decisions.jsonl").unlink()
    row = tool["audit_run"](root)
    assert row["status"] != "VALID" and row["task_outcome"] == "INCONCLUSIVE"
    assert row["whole_episode"]["action_counts"] is None
    assert row["gate_review"]["collision"]["qualifying_recent_contacts"] is None
    assert row["existing_taxonomy"]["primary_family"] is None


def test_gate_explanation_preserves_unknown_and_does_not_classify(tool):
    t = {
        "measurements": {
            "terminal_progress": {"stalled": False},
            "geometry": {"goal_disk_covered_through_window_by": ["box"]},
            "blocked_tools": [],
        },
        "thresholds": {
            "recent_contact_s": 2,
            "blocked_tool_count": 2,
            "blocked_tool_window_s": 10,
            "near_obstacle_m": 0.55,
        },
    }
    before = copy.deepcopy(t)
    review = tool["gate_review"](t)
    assert review["goal_occupied"]["covering_objects"] == ["box"]
    assert review["goal_occupied"]["stalled"] is False
    assert review["collision"]["qualifying_recent_contacts"] is None
    assert "primary_family" not in review
    assert t == before
