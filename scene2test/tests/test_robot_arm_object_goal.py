"""Guard independent suite probes against replay and mismatched checkpoints."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location("object_goal", TOOLS / "run_robot_arm_object_goal.py")
arm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(arm)


def test_suite_model_mismatch_rejected(tmp_path):
    config = arm.load(arm.DEFAULT)
    config["cases"][0]["model_path"] = "/models/libero_spatial"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="suite/checkpoint mismatch"):
        arm.load(path)


def test_existing_intent_never_dispatches(tmp_path, monkeypatch):
    case = tmp_path / "libero_object"
    case.mkdir()
    (case / "intent.json").write_text("{}")

    def forbidden(*args, **kwargs):
        pytest.fail("existing run must not probe or dispatch")

    monkeypatch.setattr(arm, "resources", forbidden)
    monkeypatch.setattr(arm.subprocess, "Popen", forbidden)
    with pytest.raises(ValueError, match="no automatic replay"):
        arm.run(arm.load(arm.DEFAULT), tmp_path)
    assert (case / "intent.json").read_text() == "{}"


def test_source_drift_rejected(tmp_path):
    path = tmp_path / "source.py"
    path.write_text("old")
    frozen = {"hashes": {str(path): arm.digest(path)}}
    path.write_text("new")
    with pytest.raises(ValueError, match="frozen source/model changed"):
        arm.verify(frozen)
