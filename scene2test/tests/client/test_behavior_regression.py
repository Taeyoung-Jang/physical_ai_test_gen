"""Injected subprocess/archives only: no network, GPU or remote model assertions."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.behavior_regression import (
    BehaviorRegression,
    memory_paths,
    replay_plan,
)
from failure_client.experiments.local_goal_adapter import atomic_json

from .test_behavior_memory import _rebind
from .test_corridor_campaign import archive
from .test_discovery_measures import json_write


def fingerprint(config):
    return {"code": "synthetic-current", "robot_resources": {"robot.xml": "f" * 64}}


class Robot:
    def __init__(self, outcomes=("PASS", "PASS"), *, crash=False, wrong_model=False):
        self.calls = []
        self.outcomes = outcomes
        self.crash = crash
        self.wrong_model = wrong_model

    def __call__(self, config, directory, parameters):
        directory.mkdir(parents=True, exist_ok=False)
        self.calls.append(directory.name)
        root = archive(
            directory / "rollout",
            scene=config.scene(parameters),
            outcome=self.outcomes[len(self.calls) - 1],
        )
        protocol = read_json(root / "protocol.json")
        protocol.update(
            model="wrong" if self.wrong_model else config.robot.model,
            http_read_timeout_s=config.robot.response_timeout,
            source_hashes={"runner": "e" * 64},
        )
        json_write(root / "protocol.json", protocol)
        rows = [json.loads(s) for s in (root / "decisions.jsonl").read_text().splitlines()]
        for row in rows:
            if "provider" in row:
                row["provider"]["request_id"] = directory.name
        (root / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        _rebind(root)
        receipt = {"returncode": 0, "interrupted": None, "wall_s": 0.01}
        atomic_json(directory / "receipt.json", receipt)
        if self.crash:
            raise RuntimeError("injected interruption after child completion")
        return receipt


def setup(tmp_path, *, outcome="PASS", repeats=2, robot=None):
    baseline = archive(tmp_path / "baseline", outcome=outcome)
    plan = replay_plan([baseline], repeats=repeats)
    root = BehaviorRegression.create(
        tmp_path / "suite", plan, fingerprint=fingerprint, execution_origin="mock"
    )
    runner = robot or Robot()
    return baseline, BehaviorRegression(root, runner=runner, fingerprint=fingerprint), runner


def test_plan_is_readonly_bounded_and_deduplicated(tmp_path):
    root = archive(tmp_path / "baseline")
    before = sorted(tmp_path.rglob("*"))
    plan = replay_plan([root, root], repeats=2, model="target-model")
    assert len(plan["cases"]) == 1 and plan["duplicates_excluded"]
    assert plan["max_attempts"] == 2 and plan["robot_api_call_upper_bound"] == 20
    assert plan["cases"][0]["target_config"]["robot"]["max_seconds"] is None
    assert sorted(tmp_path.rglob("*")) == before
    for value in (0, 11, True):
        with pytest.raises(ValueError):
            replay_plan([root], repeats=value)


@pytest.mark.parametrize(
    "baseline,outcomes,label",
    [
        ("PASS", ("PASS", "PASS"), "RETAINED_PASS"),
        ("PASS", ("FAIL", "FAIL"), "OBSERVED_REGRESSION"),
        ("FAIL", ("PASS", "PASS"), "OBSERVED_IMPROVEMENT"),
        ("FAIL", ("FAIL", "FAIL"), "RETAINED_FAIL"),
        ("PASS", ("PASS", "FAIL"), "MIXED"),
    ],
)
def test_goal_comparison_and_fixed_budget(tmp_path, baseline, outcomes, label):
    source, suite, robot = setup(tmp_path, outcome=baseline, robot=Robot(outcomes))
    manifest = (source / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="live"):
        suite.run()
    suite.run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 1 and suite.summary()["cases"][0]["comparison"] == "PENDING"
    suite.run(live=True)
    assert suite.summary()["status"] == "COMPLETE"
    assert suite.summary()["cases"][0]["comparison"] == label
    suite.run(live=True)
    assert len(robot.calls) == 2
    assert (source / "manifest.json").read_bytes() == manifest
    report = suite.report()
    assert report.exists() and "MP4" in report.read_text()
    assert not list(suite.root.rglob("*.gif")) == []  # fake source archives retain legacy GIF only
    assert not list(report.parent.glob("*.gif"))
    assert suite.state["attempts"][0]["protocol_differences"]["source_hashes"]


def test_completed_pending_collected_without_resend(tmp_path):
    _, suite, robot = setup(tmp_path, robot=Robot(crash=True))
    with pytest.raises(RuntimeError, match="injected"):
        suite.run(live=True)
    assert suite.state["pending"] == 0 and len(robot.calls) == 1
    resumed = BehaviorRegression(suite.root, runner=robot, fingerprint=fingerprint)
    resumed.run(live=True, max_new_attempts=0)
    assert resumed.state["pending"] is None and len(robot.calls) == 1
    assert resumed.summary()["cases"][0]["pass"] == 1


def test_ambiguous_pending_never_resends_and_explicit_exclusion_consumes_budget(tmp_path):
    def interrupted(*args):
        raise RuntimeError("before child metadata")

    _, suite, _ = setup(tmp_path, repeats=1, robot=interrupted)
    with pytest.raises(RuntimeError):
        suite.run(live=True)
    with pytest.raises(RuntimeError, match="ambiguous"):
        suite.run(live=True)
    suite.exclude_pending(note="inspected: child was never started")
    assert suite.state["status"] == "NEEDS_ATTENTION"
    suite.run(live=True, continue_after_exclusion=True)
    assert suite.summary()["cases"][0]["comparison"] == "INCONCLUSIVE"
    assert suite.summary()["status"] == "COMPLETE_WITH_EXCLUSIONS"


def test_active_child_cannot_be_collected_or_abandoned(tmp_path):
    def interrupted(cfg, directory, params):
        atomic_json(directory / "process.json", {"pid": os.getpid()})
        raise RuntimeError("active")

    _, suite, _ = setup(tmp_path, robot=interrupted)
    with pytest.raises(RuntimeError):
        suite.run(live=True)
    with pytest.raises(RuntimeError, match="active"):
        suite.run(live=True)
    with pytest.raises(RuntimeError, match="active"):
        suite.exclude_pending(note="not safe to abandon")


def test_wrong_contract_is_excluded_not_goal_failure(tmp_path):
    _, suite, robot = setup(tmp_path, robot=Robot(wrong_model=True))
    suite.run(live=True)
    assert suite.state["status"] == "NEEDS_ATTENTION"
    assert suite.state["attempts"][0]["episode"]["task_outcome"] == "INCONCLUSIVE"
    suite.run(live=True)
    assert len(robot.calls) == 1
    assert suite.summary()["cases"][0]["excluded"] == 1


def test_frozen_environment_and_source_tampering_stop_before_launch(tmp_path):
    source, suite, robot = setup(tmp_path)
    suite.fingerprint = lambda c: {"changed": True}
    with pytest.raises(RuntimeError, match="frozen"):
        suite.run(live=True)
    suite.fingerprint = fingerprint
    (source / "states.jsonl").write_text("tampered")
    with pytest.raises(ValueError):
        suite.run(live=True)
    assert robot.calls == []


def test_resources_mock_origins_and_source_output_are_guarded(tmp_path):
    root = archive(tmp_path / "baseline")
    plan = replay_plan([root])
    with pytest.raises(ValueError, match="origins"):
        BehaviorRegression.create(tmp_path / "live", plan, fingerprint=fingerprint)
    with pytest.raises(ValueError, match="resources"):
        BehaviorRegression.create(
            tmp_path / "changed",
            plan,
            fingerprint=lambda c: {"robot_resources": {}},
            execution_origin="mock",
        )
    with pytest.raises(ValueError, match="separate"):
        BehaviorRegression.create(
            root / "new", plan, fingerprint=fingerprint, execution_origin="mock"
        )


def test_cli_plan_needs_no_key_or_gpu(tmp_path):
    source = archive(tmp_path / "baseline")
    project = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
    result = subprocess.run(
        [
            sys.executable,
            str(project / "tools/run_behavior_regression.py"),
            "plan",
            "--run",
            str(source),
        ],
        cwd=project,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert '"robot_api_call_upper_bound": 20' in result.stdout


def test_memory_index_revalidates_sources(tmp_path):
    from failure_client.archive.regression_cases import build_failure_memory

    from .test_discovery_measures import load

    source = archive(tmp_path / "baseline")
    path = tmp_path / "memory.json"
    json_write(path, build_failure_memory([load(source)]))
    assert memory_paths(path) == [str(source)]
    (source / "result.json").write_text("{}")
    with pytest.raises(ValueError, match="missing or changed"):
        memory_paths(path)
