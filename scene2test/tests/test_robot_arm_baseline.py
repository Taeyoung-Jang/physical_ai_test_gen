"""Offline guards for the separate external-policy baseline."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[1] / "tools/run_robot_arm_baseline.py"
spec = importlib.util.spec_from_file_location("arm_baseline", TOOL)
arm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arm)


def test_plan_is_bounded_and_offline(tmp_path):
    c = arm.load(arm.DEFAULT)
    p = arm.plan(c, tmp_path / "new")
    assert p["episodes"] == 2 and p["robot_step_upper_bound"] == 600
    assert not p["afs_connected"] and p["outcomes"] is None
    assert not (tmp_path / "new").exists()
    assert len(p["commands"]) == 2
    assert len(p["source_hashes"]) == 8


def test_missing_resources_are_not_ready(tmp_path):
    c = arm.load(arm.DEFAULT)
    c.update(model_path=str(tmp_path / "missing"), python=str(tmp_path / "python"))
    assert not arm.check(c)["ready_for_attempt"]


def test_rejects_changed_experiment_contract(tmp_path):
    c = arm.load(arm.DEFAULT)
    c["environment_changes"] = ["obstacle"]
    p = tmp_path / "config.json"
    p.write_text(json.dumps(c))
    with pytest.raises(ValueError, match="contract"):
        arm.load(p)


def test_run_requires_explicit_live(tmp_path):
    r = subprocess.run(
        [sys.executable, str(TOOL), "run", "--output", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0 and "explicit --live" in r.stderr
    assert not list(tmp_path.iterdir())


def test_worker_refuses_source_drift_before_gpu_import(tmp_path):
    c = arm.load(arm.DEFAULT)
    source = tmp_path / "source.py"
    source.write_text("old")
    frozen = {"config": c, "source_hashes": {str(source): arm.digest(source)}}
    (tmp_path / "plan.json").write_text(json.dumps(frozen))
    source.write_text("new")
    with pytest.raises(ValueError, match="source changed"):
        arm.worker(c, tmp_path, 0)


def test_exclusive_write_does_not_replace_attempt(tmp_path):
    p = tmp_path / "intent.json"
    arm.write(p, {"spent": True})
    with pytest.raises(FileExistsError):
        arm.write(p, {"spent": False})
    assert json.loads(p.read_text()) == {"spent": True}


def test_existing_execution_reports_cause_without_hashing_or_dispatch(tmp_path):
    (tmp_path / "execution_intent.json").write_text("{}")
    attempt = tmp_path / "attempt_00000"
    attempt.mkdir()
    (attempt / "run.log").write_text("GatedRepoError: nvidia/Cosmos-Reason2-2B")
    r = subprocess.run(
        [
            sys.executable,
            str(TOOL),
            "run",
            "--live",
            "--config",
            str(tmp_path / "nonexistent.json"),
            "--output",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "gated_backbone_access_denied" in r.stdout
    assert "FileExistsError" not in r.stderr
    assert not (tmp_path / "attempt_00001").exists()


def test_presence_does_not_certify_backbone_access(tmp_path):
    c = arm.load(arm.DEFAULT)
    c.update(model_path=str(tmp_path), python=str(tmp_path / "missing-python"))
    result = arm.check(c)
    assert result["backbone_access"]["status"] == "UNVERIFIED"
    assert result["ready_for_attempt"] is not True
