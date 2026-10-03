"""Synthetic reference calculations, NOT a human-risk discovery benchmark."""

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from failure_client.evaluation.failure_taxonomy import RULES
from failure_client.evaluation.human_proximity import (
    HumanProximityContract,
    measure_human_proximity,
)

PROJECT = Path(__file__).resolve().parents[2]


def contract():
    return {
        "start_s": 0.0,
        "end_s": 1.0,
        "robot_base_radius_m": 0.4,
        "proxies": [{"id": "person", "center_xy_m": [0.0, 0.0], "protected_radius_m": 0.6}],
    }


def samples(x=0.5):
    return [{"time_s": i / 4, "base_xy_m": [x, 0.0]} for i in range(5)]


@pytest.mark.parametrize("outcome", ["PASS", "FAIL", "INCONCLUSIVE"])
def test_exposure_never_changes_goal_or_counts_as_fourth_family(outcome):
    r = measure_human_proximity(contract(), samples(), task_outcome=outcome)
    assert r["measurement_status"] == "AVAILABLE"
    assert r["diagnostic_status"] == "EXPOSURE_DETECTED"
    assert r["task_outcome"] == outcome
    assert r["eligible_for_family_coverage"] is False
    assert r["family_detector_status"] == "NOT_REGISTERED"
    assert "human_safety_risk" not in RULES
    z = r["zones"][0]
    assert z["min_clearance_m"] == pytest.approx(-0.5)
    assert z["exposure_duration_s"] == z["longest_continuous_exposure_s"] == 1.0


@pytest.mark.parametrize("x", [1.0, 2.0, -2.0])
def test_touch_or_clear_is_not_positive_exposure(x):
    r = measure_human_proximity(contract(), samples(x), task_outcome="FAIL")
    assert r["diagnostic_status"] == "NOT_DETECTED"
    assert r["zones"][0]["exposure_duration_s"] == 0


def test_linear_crossing_measures_sub_sample_interval_and_closest_distance():
    c = contract()
    c.update(end_s=0.25, min_continuous_exposure_s=0.1)
    rows = [{"time_s": 0.0, "base_xy_m": [-2.0, 0.0]}, {"time_s": 0.25, "base_xy_m": [2.0, 0.0]}]
    r = measure_human_proximity(c, rows, task_outcome="PASS")
    z = r["zones"][0]
    assert z["intervals_s"] == [[0.0625, 0.1875]]
    assert z["exposure_duration_s"] == pytest.approx(0.125)
    assert z["min_clearance_m"] == pytest.approx(-1.0)


def test_disjoint_short_exposures_do_not_become_sustained():
    c = contract()
    rows = samples()
    for i, row in enumerate(rows):
        row["base_xy_m"] = [0.5 if i % 2 == 0 else 2.0, 0.0]
    r = measure_human_proximity(c, rows, task_outcome="FAIL")
    assert r["zones"][0]["longest_continuous_exposure_s"] < 0.5
    assert r["diagnostic_status"] == "NOT_DETECTED"


def test_multiple_proxies_are_measured_separately():
    c = contract()
    c["proxies"].append({"id": "far", "center_xy_m": [5.0, 0.0], "protected_radius_m": 0.6})
    before = copy.deepcopy(c)
    r = measure_human_proximity(c, samples(), task_outcome="PASS")
    assert [z["sustained_exposure"] for z in r["zones"]] == [True, False]
    assert c == before


@pytest.mark.parametrize("rows", [[], samples()[:1], samples()[1:], samples()[:-1], samples()[::2]])
def test_missing_or_gapped_window_is_unknown_not_zero(rows):
    r = measure_human_proximity(contract(), rows, task_outcome="FAIL")
    assert r["measurement_status"] == r["diagnostic_status"] == "UNKNOWN"
    assert r["zones"] == []
    assert r["reason"] == "incomplete_or_gapped_window"


def test_missing_proxy_annotations_are_unsupported_not_no_risk():
    c = contract()
    c["proxies"] = []
    r = measure_human_proximity(c, samples(), task_outcome="PASS")
    assert r["measurement_status"] == "UNSUPPORTED" and r["zones"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"end_s": 0.0},
        {"start_s": 2.0},
        {"frame": "camera"},
        {"robot_base_radius_m": 0.0},
        {"max_sample_gap_s": 1.0},
        {"min_continuous_exposure_s": 0.0},
        {"goal_override": "FAIL"},
        {"end_s": float("inf")},
    ],
)
def test_contract_rejects_invalid_or_undeclared_semantics(change):
    with pytest.raises(ValueError):
        HumanProximityContract.model_validate({**contract(), **change})


def test_duplicate_proxy_times_nonfinite_and_extreme_coordinates_rejected():
    c = contract()
    c["proxies"] *= 2
    with pytest.raises(ValueError, match="distinct"):
        measure_human_proximity(c, samples(), task_outcome="FAIL")
    rows = samples()
    rows[1]["time_s"] = rows[0]["time_s"]
    with pytest.raises(ValueError, match="increasing"):
        measure_human_proximity(contract(), rows, task_outcome="FAIL")
    for x in (float("nan"), float("inf"), 1e308):
        with pytest.raises(ValueError):
            measure_human_proximity(contract(), samples(x), task_outcome="FAIL")
    with pytest.raises(ValueError):
        measure_human_proximity(contract(), samples(), task_outcome="SAFE")


def test_cli_synthetic_example_preserves_pass_and_refuses_overwrite(tmp_path):
    dest = tmp_path / "measurement"
    cli = [
        sys.executable,
        str(PROJECT / "tools/measure_human_proximity.py"),
        "--input",
        str(PROJECT / "config/measurement/human_proximity_example.json"),
    ]
    out = subprocess.run(cli + ["--output-dir", str(dest)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    r = json.loads((dest / "measurement.json").read_text())
    assert r["input_origin"] == "synthetic_fixture" and r["task_outcome"] == "PASS"
    assert r["diagnostic_status"] == "EXPOSURE_DETECTED"
    manifest = json.loads((dest / "manifest.json").read_text())
    for name, sha in manifest["files"].items():
        assert hashlib.sha256((dest / name).read_bytes()).hexdigest() == sha
    again = subprocess.run(cli + ["--output-dir", str(dest)], capture_output=True, text=True)
    assert again.returncode == 2 and "FileExistsError" in again.stderr
    stdout = subprocess.run(cli + ["--stdout-only"], capture_output=True, text=True)
    assert stdout.returncode == 0 and json.loads(stdout.stdout) == r
