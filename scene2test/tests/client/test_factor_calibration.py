"""Offline factor calibration guards and fake execution; no paid calls."""

from copy import deepcopy

import pytest

from clear_path.contracts import HumanFixture
from failure_client.experiments.afs_contrast import factor_plan, validate_plan
from failure_client.experiments.behavior_regression import BehaviorRegression

from .test_afs_contrast import Robot, fingerprint, source

PROBES = [
    {"axis": "corridor_width_m", "value": 2.8},
    {"axis": "floor_friction", "value": 0.5},
    {"axis": "human_lateral_fraction", "value": -0.8},
]


def prepared(tmp_path, robot=None):
    a = source(tmp_path / "a", outcome="PASS", scene=HumanFixture())
    b = source(tmp_path / "b", outcome="FAIL", scene=HumanFixture())
    plan = factor_plan([a, b], probes=PROBES)
    root = BehaviorRegression.create(
        tmp_path / "suite", plan, fingerprint=fingerprint, execution_origin="mock"
    )
    robot = robot or Robot()
    return plan, BehaviorRegression(root, runner=robot, fingerprint=fingerprint), robot


def test_shared_mixed_control_fixed_matrix_and_complete_batch(tmp_path):
    plan, suite, robot = prepared(tmp_path)
    assert plan["max_attempts"] == 8 and plan["robot_api_call_upper_bound"] == 80
    assert plan["afs_requests"] == 0 and len(plan["history"]) == 2
    assert plan["cases"][0]["baseline_pass"] == plan["cases"][0]["baseline_fail"] == 1
    for case in plan["cases"][1:]:
        assert {k for k, v in plan["reference_scene"].items() if v != case["scene"][k]} == {
            case["changed_axis"]
        }
    suite.run(live=True)
    assert len(robot.calls) == 8 and suite.summary()["status"] == "COMPLETE"
    assert [c["changed_axis"] for c in suite.summary()["cases"]] == [
        None,
        "corridor_width_m",
        "floor_friction",
        "human_lateral_fraction",
    ]
    assert all(c["comparison"].startswith("OBSERVED_") for c in suite.summary()["cases"])
    assert suite.report().is_file()
    suite.run(live=True)
    assert len(robot.calls) == 8


@pytest.mark.parametrize("mutation", ["extra_axis", "value", "role", "budget", "unknown"])
def test_matrix_tampering_rejected(tmp_path, mutation):
    plan, _, _ = prepared(tmp_path)
    plan = deepcopy(plan)
    if mutation == "extra_axis":
        plan["cases"][1]["scene"]["box_mass_kg"] += 1
    elif mutation == "value":
        plan["factors"][0]["value"] = 3.2
    elif mutation == "role":
        plan["cases"][2]["changed_axis"] = "corridor_width_m"
    elif mutation == "budget":
        plan["max_attempts"] += 1
    else:
        plan["design"] = "unknown"
    with pytest.raises(ValueError):
        validate_plan(plan)


def test_exclusion_stops_and_resume_advances_without_replacement(tmp_path):
    _, suite, robot = prepared(tmp_path, Robot(excluded=True))
    assert suite.run(live=True)["status"] == "NEEDS_ATTENTION"
    suite.run(live=True)
    assert len(robot.calls) == 1
    robot.excluded = False
    suite.run(live=True, continue_after_exclusion=True)
    assert len(robot.calls) == 8
    assert suite.summary()["status"] == "COMPLETE_WITH_EXCLUSIONS"
    assert suite.summary()["cases"][0]["excluded"] == 1


def test_saved_receipt_resume_does_not_relaunch(tmp_path):
    _, suite, robot = prepared(tmp_path, Robot(crash=True))
    with pytest.raises(RuntimeError, match="crash"):
        suite.run(live=True)
    robot.crash = False
    suite.run(live=True, max_new_attempts=0)
    assert len(robot.calls) == 1 and suite.summary()["pending"] is None
    suite.run(live=True)
    assert len(robot.calls) == 8
