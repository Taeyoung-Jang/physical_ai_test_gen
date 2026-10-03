"""One-command workflow tests with synthetic robot archives; no paid API/GPU runs."""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.research_campaign import ResearchCampaign
from failure_client.experiments.research_protocol import CampaignConfig, RobotSettings

from .test_research_campaign import FakeProposer, FakeRobot, frozen, reload, setup

TOOL = Path(__file__).resolve().parents[2] / "tools/run_afs_pilot.py"


@pytest.fixture
def pilot():
    spec = importlib.util.spec_from_file_location("afs_pilot", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def small_config():
    return CampaignConfig(
        robot=RobotSettings(model="synthetic-mock"), valid_budget_per_seed=3, cold_start=1
    )


def journal(engine):
    return sorted((engine.root / "pilot_runs").iterdir())[-1]


def test_plan_only_with_key_has_no_side_effects_from_other_cwd(tmp_path):
    output = tmp_path / "not-created"
    result = subprocess.run(
        [sys.executable, str(TOOL), "--output-dir", str(output)],
        cwd=tmp_path,
        env={
            **os.environ,
            "OPENAI_API_KEY": "synthetic-key-must-not-be-used",
            "PYTHONPATH": str(TOOL.parents[1] / "src"),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "PLAN_ONLY" in result.stdout and "synthetic-key" not in result.stdout
    plan = json.loads(result.stdout.splitlines()[0].removeprefix("PILOT_PLAN="))
    assert plan["valid_rollouts_total"] == 16
    assert plan["robot_api_call_upper_bound"] == 240
    assert plan["afs_request_upper_bound"] == 8
    assert plan["max_simulation_s"] is None
    assert not output.exists()


@pytest.mark.parametrize("key", [None, "", "   "])
def test_live_requires_key_before_creating_output(pilot, tmp_path, monkeypatch, key):
    if key is None:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", key)
    with pytest.raises(SystemExit) as error:
        pilot.main(["--live", "--output-dir", str(tmp_path / "out")])
    assert error.value.code == 2
    assert not (tmp_path / "out").exists()


def test_one_command_creates_completes_and_reports(pilot, tmp_path, monkeypatch):
    robot, proposer = FakeRobot(), FakeProposer()

    class SyntheticCampaign:
        @staticmethod
        def create(root, config):
            return ResearchCampaign.create(
                root, config, fingerprint=frozen, execution_origin="mock"
            )

        def __new__(cls, root):
            return ResearchCampaign(root, runner=robot, proposer=proposer, fingerprint=frozen)

    monkeypatch.setattr(pilot, "ResearchCampaign", SyntheticCampaign)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-never-sent")
    root = tmp_path / "campaign"
    assert pilot.main(["--live", "--output-dir", str(root)]) == 0
    engine = SyntheticCampaign(root)
    assert engine.summary()["status"] == "COMPLETE"
    assert [arm["valid"] for arm in engine.summary()["arms"]] == [8, 8]
    assert len(robot.calls) == 16
    log = journal(engine)
    first = read_json(log / "initial_check.json")
    assert sum(arm["valid"] for arm in first["arms"]) == 2
    assert read_json(log / "summary.json")["exit_code"] == 0
    assert (log / "events.jsonl").exists()
    report = Path(read_json(root / "latest_report.json")["report"])
    assert report.is_file() and (report.parent / "memory/index.html").is_file()
    assert len(list((root / "reports").iterdir())) == 2
    before = (len(robot.calls), len(proposer.calls))
    assert pilot.main(["--live", "--campaign", str(root)]) == 0
    assert (len(robot.calls), len(proposer.calls)) == before
    assert len(list((root / "pilot_runs").iterdir())) == 2
    # A second NEW invocation must not overwrite an existing campaign.
    assert pilot.main(["--live", "--output-dir", str(root)]) == 2
    assert (len(robot.calls), len(proposer.calls)) == before


def test_staged_execution_matches_existing_uninterrupted_candidates(pilot, tmp_path):
    direct, robot_a, proposer_a = setup(tmp_path / "direct", config=small_config())
    staged, robot_b, proposer_b = setup(tmp_path / "staged", config=small_config())
    direct.run()
    assert pilot.execute(staged) == 0
    assert robot_a.calls == robot_b.calls
    assert len(proposer_a.calls) == len(proposer_b.calls)
    assert any(record.task_outcome == "FAIL" for record in staged.records())


@pytest.mark.parametrize("fault", ["incomplete", "watchdog", "keyboard"])
def test_execution_fault_stops_before_next_attempt_and_keeps_partial_report(pilot, tmp_path, fault):
    engine, robot, _ = setup(tmp_path, config=small_config())
    calls = []

    def failed(config, directory, params):
        calls.append(1)
        if fault == "keyboard":
            raise KeyboardInterrupt()
        if fault == "incomplete":
            return {"returncode": 1, "wall_s": 0.1, "interrupted": None}
        receipt = robot(config, directory, params)
        receipt["interrupted"] = "TimeoutExpired"
        return receipt

    engine.runner = failed
    assert pilot.execute(engine) == (130 if fault == "keyboard" else 2)
    assert len(calls) == 1
    assert (journal(engine) / "error.json").exists()
    assert (engine.root / "latest_report.json").exists()
    assert all(arm["valid"] == 0 for arm in engine.summary()["arms"])


def test_uncertain_proposal_never_retried_and_error_redacted(pilot, tmp_path, monkeypatch):
    engine, robot, _ = setup(tmp_path, config=small_config())
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-private-value")

    def failed(*_, **__):
        calls.append(1)
        raise RuntimeError("synthetic-private-value transport completion unknown")

    engine.proposer = failed
    assert pilot.execute(engine) == 2
    before = len(robot.calls)
    engine = reload(engine, robot, failed)
    assert pilot.execute(engine) == 2
    assert len(calls) == 1 and len(robot.calls) == before
    assert engine.summary()["pending"]["kind"] == "proposal"
    for log in (engine.root / "pilot_runs").iterdir():
        assert "synthetic-private-value" not in (log / "error.json").read_text()


def test_report_failure_is_not_hidden_by_successful_rollouts(pilot, tmp_path, monkeypatch):
    engine, robot, _ = setup(tmp_path, config=small_config())

    def failed_report(**_):
        raise OSError("synthetic report failure")

    monkeypatch.setattr(engine, "report", failed_report)
    assert pilot.execute(engine) == 2
    assert len(robot.calls) == 2
    assert (journal(engine) / "error.json").exists()
    assert (journal(engine) / "report_error.json").exists()
    assert read_json(journal(engine) / "summary.json")["exit_code"] == 2


def test_recovered_incomplete_archive_stops_before_new_launch(pilot, tmp_path):
    engine, robot, proposer = setup(tmp_path, config=small_config())

    def crashed(*_):
        raise SystemExit("driver crash")

    engine.runner = crashed
    with pytest.raises(SystemExit):
        engine.run()
    # Receipt proves that the child ended, but does not make missing evidence valid.
    receipt = engine.root / "attempts/attempt_00000/receipt.json"
    receipt.write_text(json.dumps({"returncode": 1, "interrupted": None, "wall_s": 0.1}))
    engine = reload(engine, robot, proposer)
    assert pilot.execute(engine) == 2
    assert len(robot.calls) == 0
    assert engine.records()[0].status == "INCOMPLETE"


def test_resume_cannot_override_frozen_config(pilot, tmp_path):
    with pytest.raises(SystemExit) as error:
        pilot.main(["--campaign", str(tmp_path), "--config", "different.json"])
    assert error.value.code == 2


def test_code_drift_stops_before_launch(pilot, tmp_path):
    engine, robot, _ = setup(tmp_path, config=small_config())
    engine.fingerprint = lambda _: {"changed": True}
    assert pilot.execute(engine) == 2
    assert not robot.calls


def test_incomplete_campaign_never_starts_new_attempts(pilot, tmp_path):
    engine, _, _ = setup(tmp_path, config=small_config())
    calls = []

    def failed(*_):
        calls.append(1)
        return {"returncode": 1, "wall_s": 0.1, "interrupted": None}

    engine.runner = failed
    assert engine.run()["status"] == "INCOMPLETE"
    before = len(calls)
    assert pilot.execute(engine) == 2
    assert len(calls) == before
    assert read_json(journal(engine) / "summary.json")["status"] == "INCOMPLETE"


def test_unchanged_pending_archive_is_recovered_without_reexecution(pilot, tmp_path):
    engine, robot, proposer = setup(tmp_path, config=small_config())

    def crash(config, directory, params):
        robot(config, directory, params)
        raise SystemExit("archive persisted, checkpoint not committed")

    engine.runner = crash
    with pytest.raises(SystemExit):
        engine.run()
    assert len(robot.calls) == 1
    engine = reload(engine, robot, proposer)
    assert pilot.execute(engine) == 0
    assert len(robot.calls) == 6  # Includes the recovered one, never seven.
    assert [arm["valid"] for arm in engine.summary()["arms"]] == [3, 3]
