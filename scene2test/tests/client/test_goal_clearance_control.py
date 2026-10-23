"""Synthetic clear-goal preparation and bounded probe-only execution."""

import json
import runpy
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from clear_path.contracts import HumanFixture
from failure_client.experiments.afs_contrast import probe_validation_plan, validate_plan
from failure_client.experiments.behavior_regression import BehaviorRegression

from .test_afs_contrast import Robot, fingerprint, source
from .test_behavior_memory import _rebind
from .test_discovery_measures import json_write


def baseline(tmp_path):
    scene = HumanFixture(corridor_width_m=3.6, box_lateral_fraction=0.5)
    return [
        source(tmp_path / "fail", scene=scene, outcome="FAIL"),
        source(tmp_path / "pass", scene=scene, outcome="PASS"),
    ]


def test_only_changed_scene_two_repeats_and_report(tmp_path):
    plan = probe_validation_plan(baseline(tmp_path), axis="box_lateral_fraction", value=1.0)
    assert len(plan["cases"]) == 1 and plan["max_attempts"] == 2
    assert plan["robot_api_call_upper_bound"] == 20 and plan["afs_requests"] == 0
    assert plan["cases"][0]["baseline_pass"] == plan["cases"][0]["baseline_fail"] == 1
    root = BehaviorRegression.create(
        tmp_path / "suite", plan, fingerprint=fingerprint, execution_origin="mock"
    )
    robot = Robot()
    suite = BehaviorRegression(root, runner=robot, fingerprint=fingerprint)
    suite.run(live=True)
    assert suite.summary()["status"] == "COMPLETE" and len(robot.calls) == 2
    assert all(p["box_lateral_fraction"] == 1.0 for p in robot.calls)
    assert suite.summary()["cases"][0]["comparison"] == "OBSERVED_PASS"
    assert suite.report().is_file()
    suite.run(live=True)
    assert len(robot.calls) == 2


@pytest.mark.parametrize("change", ["duplicate", "extra_axis", "control_role", "budget"])
def test_probe_guards(tmp_path, change):
    p = probe_validation_plan(baseline(tmp_path), axis="box_lateral_fraction", value=1.0)
    if change == "duplicate":
        c = deepcopy(p["cases"][0])
        c["case_id"] += "x"
        p["cases"].append(c)
    elif change == "extra_axis":
        p["cases"][0]["scene"]["floor_friction"] = 0.3
    elif change == "control_role":
        p["cases"][0]["contrast_role"] = "control_repeat"
    else:
        p["max_attempts"] = 3
    with pytest.raises(ValueError):
        validate_plan(p)


def test_probe_exclusion_stops_without_replacement(tmp_path):
    p = probe_validation_plan(baseline(tmp_path), axis="box_lateral_fraction", value=1.0)
    root = BehaviorRegression.create(
        tmp_path / "suite", p, fingerprint=fingerprint, execution_origin="mock"
    )
    robot = Robot(excluded=True)
    suite = BehaviorRegression(root, runner=robot, fingerprint=fingerprint)
    assert suite.run(live=True)["status"] == "NEEDS_ATTENTION"
    suite.run(live=True)
    assert len(robot.calls) == 1


def test_free_preflight_and_no_path_refusal(tmp_path, monkeypatch):
    paths = baseline(tmp_path)
    for path in paths:
        protocol = json.loads((path / "protocol.json").read_text())
        protocol["source_hashes"]["navigation_tools"] = "f" * 64
        json_write(path / "protocol.json", protocol)
        _rebind(path)
    tool = Path(__file__).resolve().parents[2] / "tools/run_goal_clearance_control.py"
    prepare = runpy.run_path(str(tool))["prepare_plan"]
    original_hash = prepare.__globals__["_hash_file"]
    monkeypatch.setitem(
        prepare.__globals__,
        "_hash_file",
        lambda p: "f" * 64 if p.name == "navigation_tools.py" else original_hash(p),
    )
    observations = []

    def observation(_):
        o = SimpleNamespace(
            geometry=[SimpleNamespace(object_id="clear_box_geom", center_m=[7.0, 0.6, 0.35])]
        )
        observations.append(o)
        return o

    monkeypatch.setitem(
        prepare.__globals__, "Observation", SimpleNamespace(model_validate=observation)
    )
    monkeypatch.setitem(prepare.__globals__, "navigation_plan", lambda *_: {"status": "path_found"})
    plan = prepare(paths)
    assert len(plan["control_readiness"]["geometry_checks"]) == 2
    assert all(o.geometry[0].center_m[:2] == [7.0, 1.2] for o in observations)
    monkeypatch.setitem(prepare.__globals__, "navigation_plan", lambda *_: {"status": "no_path"})
    with pytest.raises(ValueError, match="static planner route"):
        prepare(paths)


def test_changed_planner_preflight_refused(tmp_path):
    tool = Path(__file__).resolve().parents[2] / "tools/run_goal_clearance_control.py"
    with pytest.raises(ValueError, match="archived planner"):
        runpy.run_path(str(tool))["prepare_plan"](baseline(tmp_path))
