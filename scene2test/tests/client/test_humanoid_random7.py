import copy
import json
import runpy
from pathlib import Path

import pytest

from .test_afs_contrast import Robot, fingerprint
from .test_humanoid_random_assessment import setup_random
from .test_independent_discovery import OutcomeRobot


def module():
    return runpy.run_path(str(Path(__file__).parents[2] / "tools/run_humanoid_random7.py"))


def prepared(tmp_path):
    source, _, _, factory, _ = setup_random(tmp_path, count=3)
    factory(source).run(live=True, max_new_attempts=3)
    f = module()
    root = tmp_path / "additional_four"
    f["prepare"](source, root, fingerprint_fn=fingerprint)
    return source, root, f


def test_preserves_original_and_continues_draws_without_extra_baseline(tmp_path):
    source, root, f = prepared(tmp_path)
    before = copy.deepcopy(f["support"]()["snapshot"](source))
    robot = OutcomeRobot("PASS")
    result = f["run"](root, live=True, runner=robot, fingerprint_fn=fingerprint)
    assert result["complete"] and result["valid"] == result["pass"] == 7
    assert result["afs_requests"] == 0 and len(robot.calls) == 4
    assert f["support"]()["snapshot"](source) == before
    plan = f["sealed"](root / "plan.json")
    base = before[0]["matched_local"]["base_parameters"]
    assert [sum(v != base[k] for k, v in p.items()) for p in robot.calls] == [1, 2, 1, 2]
    assert robot.calls == [r["parameters"] for r in plan["draws"]]
    assert all(Path(r["source"]["path"]).is_relative_to(source) for r in result["records"][:3])
    f["run"](root, live=True, runner=robot, fingerprint_fn=fingerprint)
    assert len(robot.calls) == 4


def test_existing_intent_never_resends_and_saved_receipt_collects(tmp_path):
    _, root, f = prepared(tmp_path)
    robot = OutcomeRobot("PASS")

    def crash(cfg, directory, params):
        robot(cfg, directory, params)
        (directory / "receipt.json").write_text(json.dumps({"returncode": 0}))
        raise RuntimeError("synthetic crash after receipt")

    with pytest.raises(RuntimeError, match="after receipt"):
        f["run"](root, live=True, runner=crash, fingerprint_fn=fingerprint)
    result = f["run"](root, live=True, runner=robot, fingerprint_fn=fingerprint)
    assert result["complete"] and len(robot.calls) == 4


def test_exclusion_stops_without_replacement(tmp_path):
    _, root, f = prepared(tmp_path)
    robot = Robot(excluded=True)
    result = f["run"](root, live=True, runner=robot, fingerprint_fn=fingerprint)
    assert result["valid"] == 3 and result["excluded"] == 1
    assert result["fail"] == 0 and not result["complete"]
    f["run"](root, live=True, runner=robot, fingerprint_fn=fingerprint)
    assert len(robot.calls) == 1
