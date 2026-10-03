"""Offline crash/TOCTOU regressions; no live policy calls or robot launches."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from failure_client.experiments.local_goal_adapter import LocalGoalRunner
from failure_client.experiments.research_campaign import NeedsAttention
from failure_client.experiments.research_protocol import CampaignConfig

from .test_behavior_memory import _rebind
from .test_discovery_measures import json_write, load, rewrite_manifest, saved_run
from .test_research_campaign import reload, setup


def test_ready_proposal_rechecks_original_evidence_before_launch(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)
    original_save = engine._save

    def crash(event, detail=None):
        original_save(event, detail)
        if event == "proposal_validated":
            raise SystemExit("validated but not launched")

    engine._save = crash
    with pytest.raises(SystemExit):
        engine.run()
    previous_calls = len(robot.calls)
    record = engine.records("afs", 17)[0]
    (Path(record.source.path) / "scene.xml").write_text("<changed/>")
    engine = reload(engine, robot, proposer)
    with pytest.raises(NeedsAttention, match="evidence changed"):
        engine.run(max_new_attempts=1)
    assert len(robot.calls) == previous_calls
    assert len(proposer.calls) == 1


@pytest.mark.parametrize("change", ["code", "evidence"])
def test_drift_during_proposal_blocks_next_robot_launch(tmp_path, change):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)
    calls_at_response = []

    def altered(body, **kwargs):
        response = proposer(body, **kwargs)
        calls_at_response.append(len(robot.calls))
        if change == "code":
            engine.fingerprint = lambda _: {"changed_while_waiting": True}
        else:
            record = engine.records("afs", 17)[0]
            (Path(record.source.path) / "scene.xml").write_text("<changed/>")
        return response

    engine.proposer = altered
    with pytest.raises(NeedsAttention):
        engine.run(max_new_attempts=2)
    assert len(robot.calls) == calls_at_response[0]
    assert len(proposer.calls) == 1


@pytest.mark.parametrize("error", [SystemExit, RuntimeError])
def test_condition_drift_stop_is_atomic_with_observation(tmp_path, error):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=1)

    def drift(config, directory, params):
        receipt = robot(config, directory, params)
        root = directory / "rollout"
        protocol = json.loads((root / "protocol.json").read_text())
        protocol["source_hashes"]["runner"] = "a" * 64
        json_write(root / "protocol.json", protocol)
        _rebind(root)
        return receipt

    engine.runner = drift
    original_save = engine._save

    def crash(event, detail=None):
        original_save(event, detail)
        if event == "observed_and_checkpointed":
            raise error("observation saved before stop ledger event")

    engine._save = crash
    with pytest.raises(error):
        engine.run(max_new_attempts=1)
    engine = reload(engine, robot, proposer)
    assert engine.summary()["status"] == "INCOMPLETE"
    assert engine.run()["reason"] == "condition_or_returned_model_changed"
    assert len(robot.calls) == 2


def test_saved_valid_response_cannot_be_abandoned_before_validation(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)

    def crash(*_):
        raise SystemExit("response saved but not validated")

    engine._finish_proposal = crash
    with pytest.raises(SystemExit):
        engine.run()
    engine = reload(engine, robot, proposer)
    before = copy.deepcopy(engine.state)
    with pytest.raises(ValueError, match="resume"):
        engine.abandon_pending("proposal_00000", "response arrived; no request is running")
    assert engine.state == before
    engine.run(max_new_attempts=1)
    assert len(proposer.calls) == 1


@pytest.mark.parametrize("fault", ["refusal", "stale"])
def test_invalid_saved_response_remains_explicitly_resolvable(tmp_path, fault):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)

    def invalid(body, **kwargs):
        response = proposer(body, **kwargs)
        if fault == "refusal":
            response["output"][0]["content"] = [{"type": "refusal", "refusal": "test"}]
        else:
            text = response["output"][0]["content"][0]
            raw = json.loads(text["text"])
            raw["context_sha256"] = "wrong"
            text["text"] = json.dumps(raw)
        return response

    engine.proposer = invalid
    with pytest.raises(NeedsAttention):
        engine.run()
    calls = len(robot.calls)
    usage = copy.deepcopy(engine.state["proposals"][0]["usage"])
    engine.abandon_pending("proposal_00000", "invalid response; no request active")
    assert engine.state["pending"] is None
    assert engine.state["proposals"][0]["status"] == "ABANDONED"
    assert engine.state["proposals"][0]["usage"] == usage
    assert len(proposer.calls) == 1 and len(robot.calls) == calls


@pytest.mark.parametrize("fault", ["metadata_write", "signal_exit_race", "kill_exit_race"])
def test_spawned_child_is_reaped_on_metadata_error_and_exit_race(tmp_path, monkeypatch, fault):
    import failure_client.experiments.local_goal_adapter as adapter

    waits, signals = [], []

    class Process:
        pid = 999999999
        returncode = None

        def wait(self, timeout=None):
            waits.append(timeout)
            if fault != "metadata_write" and timeout == 5000:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            if fault == "kill_exit_race" and timeout == 10:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            self.returncode = -15
            return self.returncode

    proc = Process()
    monkeypatch.setattr(adapter.subprocess, "Popen", lambda *_, **__: proc)

    def kill(*args):
        signals.append(args)
        if fault == "signal_exit_race" or (fault == "kill_exit_race" and len(signals) == 2):
            raise ProcessLookupError("child already exited")

    monkeypatch.setattr(adapter.os, "killpg", kill)
    original_write = adapter.atomic_json

    def write(path, value):
        if fault == "metadata_write" and Path(path).name == "process.json":
            raise OSError("synthetic metadata storage failure")
        original_write(path, value)

    monkeypatch.setattr(adapter, "atomic_json", write)
    config = CampaignConfig(robot={"watchdog_wall_s": 5000.0})
    params = {"box_mass_kg": 2.0, "box_friction": 0.5, "floor_friction": 0.8}
    if fault == "metadata_write":
        with pytest.raises(OSError, match="storage failure"):
            LocalGoalRunner()(config, tmp_path, params)
    else:
        LocalGoalRunner()(config, tmp_path, params)
    assert signals and waits
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["interrupted"] == ("OSError" if fault == "metadata_write" else "TimeoutExpired")
    assert proc.returncode is not None


@pytest.mark.parametrize("field", ["api_calls_attempted", "calls_attempted"])
@pytest.mark.parametrize("outcome", ["PASS", "FAIL"])
def test_over_budget_archive_is_not_a_valid_goal_trial(tmp_path, field, outcome):
    root = saved_run(tmp_path / "over_budget", outcome=outcome)
    result = json.loads((root / "result.json").read_text())
    result[field] = 11  # Declared max_calls is ten, even if the final goal flag is consistent.
    json_write(root / "result.json", result)
    rewrite_manifest(root)
    record = load(root)
    assert record.status == "INVALID"
    assert record.exclusion_reason == "episode_call_budget_exceeded"
    assert record.task_outcome == "INCONCLUSIVE"


def test_inconsistent_call_counters_are_rejected(tmp_path):
    root = saved_run(tmp_path / "counts")
    result = json.loads((root / "result.json").read_text())
    result.update(calls_attempted=2, api_calls_attempted=3)
    json_write(root / "result.json", result)
    rewrite_manifest(root)
    assert load(root).exclusion_reason == "inconsistent_policy_call_counts"


def test_exact_call_budget_stays_valid(tmp_path):
    root = saved_run(tmp_path / "at_budget")
    result = json.loads((root / "result.json").read_text())
    result["calls_attempted"] = 10
    json_write(root / "result.json", result)
    rewrite_manifest(root)
    assert load(root).status == "VALID"


@pytest.mark.parametrize("fault", ["metadata_write", "watchdog"])
def test_real_harmless_child_is_reaped(tmp_path, monkeypatch, fault):
    """Exercise OS process cleanup, using a sleeping Python child, never the robot CLI."""
    import failure_client.experiments.local_goal_adapter as adapter

    children = []
    original_spawn, original_write = adapter.subprocess.Popen, adapter.atomic_json

    def spawn(*args, **kwargs):
        child = original_spawn(*args, **kwargs)
        children.append(child)
        return child

    def write(path, value):
        if fault == "metadata_write" and Path(path).name == "process.json":
            raise OSError("synthetic metadata storage failure")
        original_write(path, value)

    monkeypatch.setattr(adapter.subprocess, "Popen", spawn)
    monkeypatch.setattr(adapter, "atomic_json", write)
    monkeypatch.setattr(
        adapter, "command", lambda *_: [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    config = CampaignConfig(robot={"watchdog_wall_s": 0.1})
    params = {"box_mass_kg": 2.0, "box_friction": 0.5, "floor_friction": 0.8}
    try:
        if fault == "metadata_write":
            with pytest.raises(OSError, match="storage failure"):
                LocalGoalRunner()(config, tmp_path, params)
        else:
            LocalGoalRunner()(config, tmp_path, params)
        assert len(children) == 1 and children[0].poll() is not None
        receipt = json.loads((tmp_path / "receipt.json").read_text())
        assert receipt["returncode"] == children[0].returncode
        assert receipt["interrupted"] == (
            "OSError" if fault == "metadata_write" else "TimeoutExpired"
        )
    finally:
        # Even a future cleanup regression must not leak this test's harmless child.
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)
