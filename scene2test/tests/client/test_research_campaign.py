"""P2 wiring/fault injection with synthetic archives. Never API/GPU performance evidence."""

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from clear_path.contracts import Fixture
from clear_path.fixture import identity, world_xml
from failure_client.archive.regression_cases import build_failure_memory
from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.experiments.local_goal_adapter import LocalGoalRunner, atomic_json, command
from failure_client.experiments.research_campaign import NeedsAttention, ResearchCampaign
from failure_client.experiments.research_protocol import CampaignConfig, RobotSettings
from failure_client.methods.base import CandidateObservation
from failure_client.methods.behavior_feedback import (
    BehaviorMethodState,
    boundary_candidate,
    choose_probe,
    feedback_context,
    proposal_request,
    uniform_scene,
)
from llm_afs.behavior import digest

from .test_behavior_memory import _rebind, fixture
from .test_discovery_measures import json_write, load


def frozen(_):
    return {"synthetic_environment": "not a real robot"}


class FakeRobot:
    def __init__(self):
        self.calls = []

    def __call__(self, config, directory, params):
        self.calls.append((directory.name, copy.deepcopy(params)))
        # Synthetic discontinuity is a test oracle, not a claim about G1 physics.
        outcome = "PASS" if params["box_mass_kg"] < 5 else "FAIL"
        root = fixture(
            directory / "rollout",
            outcome=outcome,
            mass=params["box_mass_kg"],
            friction=params["floor_friction"],
        )
        scene = Fixture(**params)
        protocol = read_json(root / "protocol.json")
        protocol.update(
            scene_config=scene.model_dump(),
            scene_revision=identity(scene),
            model=config.robot.model,
            http_read_timeout_s=config.robot.response_timeout,
        )
        json_write(root / "protocol.json", protocol)
        (root / "scene.xml").write_text(world_xml(scene))
        rows = [json.loads(line) for line in (root / "decisions.jsonl").read_text().splitlines()]
        for row in rows:
            if "provider" in row:
                row["provider"]["request_id"] = "synthetic-" + directory.name
        (root / "decisions.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        _rebind(root)
        return {"returncode": 0, "wall_s": 0.25, "interrupted": None}


class FakeProposer:
    def __init__(self):
        self.calls = []

    def __call__(self, body, **_):
        self.calls.append(copy.deepcopy(body))
        ctx = json.loads(body["input"][0]["content"])
        # Changing these proposals changes actual selected candidates, exercised below.
        axis = "box_mass_kg" if len(self.calls) % 2 else "floor_friction"
        low, high = (0.3, 9.7) if axis == "box_mass_kg" else (0.06, 1.45)
        raw = {
            "context_sha256": ctx["context_sha256"],
            "spaces": [
                {
                    "mode": "success_probe",
                    "axis": axis,
                    "low": low,
                    "high": high,
                    "evidence_refs": ["case_memory"],
                    "hypothesis": "synthetic hypothesis",
                    "alternative": "friction also matters",
                    "falsification": "observe opposite goal result",
                }
            ],
        }
        return {
            "status": "completed",
            "id": "synthetic-api",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 12, "output_tokens": 34},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        }


def setup(tmp_path, *, config=None, robot=None, proposer=None):
    config = config or CampaignConfig(robot=RobotSettings(model="synthetic-mock"))
    root = ResearchCampaign.create(
        tmp_path / "campaign", config, fingerprint=frozen, execution_origin="mock"
    )
    robot, proposer = robot or FakeRobot(), proposer or FakeProposer()
    engine = ResearchCampaign(root, runner=robot, proposer=proposer, fingerprint=frozen)
    return engine, robot, proposer


def reload(engine, robot, proposer):
    return ResearchCampaign(engine.root, runner=robot, proposer=proposer, fingerprint=frozen)


def test_equal_valid_budgets_cold_repeats_full_domain_and_report(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    summary = engine.run()
    assert summary["status"] == "COMPLETE"
    assert [a["valid"] for a in summary["arms"]] == [8, 8]
    assert len(robot.calls) == 16
    attempts = engine.state["attempts"]
    for method in ("afs", "random"):
        rows = [a for a in attempts if a["method"] == method]
        for i in range(2):
            assert rows[i]["candidate"]["parameters"] == uniform_scene(17, "paired-cold", i)
        assert len([a for a in rows if a["episode"]["status"] == "VALID"]) == 8
    afs = [a for a in attempts if a["method"] == "afs"]
    assert afs[4]["candidate"]["strategy"] == "independent_exploration"
    assert afs[5]["candidate"]["stage"] == "repeat"
    for i, a in enumerate(a for a in attempts if a["method"] == "random"):
        if i >= 2:
            assert a["candidate"]["parameters"] == uniform_scene(17, "random", i)
    assert proposer.calls
    assert all(a["status"] == "OBSERVED" for a in attempts)
    assert sum(len(s["observed"]) for s in engine.state["checkpoints"].values()) == 16
    report = engine.report(with_memory=True)
    metrics = read_json(report.parent / "metrics.json")
    assert metrics["comparison"]["status"] != "not_comparable"
    assert metrics["campaign_execution"]["afs_requests_attempted"] == len(proposer.calls)
    assert metrics["groups"][0]["failure_diversity_coverage"] is None
    manifest = read_json(report.parent / "manifest.json")
    for item in manifest["artifacts"]:
        assert _hash_file(report.parent / item["path"]) == item["sha256"]
    assert "Campaign 진행" in report.read_text()
    assert not list(report.parent.rglob("*.gif"))
    assert "mock" in (report.parent / "memory/index.html").read_text()


def test_resume_has_same_candidates_and_no_second_completion(tmp_path):
    a, robot_a, proposer_a = setup(tmp_path / "a")
    b, robot_b, proposer_b = setup(tmp_path / "b")
    a.run()
    b.run(max_new_attempts=5)
    b = reload(b, robot_b, proposer_b)
    b.run()
    assert robot_a.calls == robot_b.calls
    assert len(proposer_a.calls) == len(proposer_b.calls)
    before = len(robot_b.calls)
    b.run()
    assert len(robot_b.calls) == before


def test_completed_archive_after_crash_is_ingested_not_rerun(tmp_path):
    engine, robot, proposer = setup(tmp_path)

    def crash(config, directory, params):
        robot(config, directory, params)
        raise SystemExit("crash after archive, before receipt/checkpoint")

    engine.runner = crash
    with pytest.raises(SystemExit):
        engine.run()
    assert len(robot.calls) == 1
    engine = reload(engine, robot, proposer)
    engine.run(max_new_attempts=0)
    assert len(robot.calls) == 1
    assert len(engine.records()) == 1
    assert engine.records()[0].status == "VALID"
    engine.run()
    assert len(robot.calls) == 16


def test_unknown_execution_never_relaunched_until_explicit_resolution(tmp_path):
    engine, robot, proposer = setup(tmp_path)

    def crash(*_):
        raise SystemExit("may have launched")

    engine.runner = crash
    with pytest.raises(SystemExit):
        engine.run()
    engine = reload(engine, robot, proposer)
    with pytest.raises(NeedsAttention, match="ambiguous"):
        engine.run()
    assert not robot.calls
    engine.abandon_pending("attempt_00000", "operator verified no child is active")
    assert engine.records()[0].status == "INCONCLUSIVE"
    engine.run()
    assert len(robot.calls) == 16
    assert len(engine.state["attempts"]) == 17


def test_running_process_blocks_abandon(tmp_path):
    engine, _, _ = setup(tmp_path)
    with engine.store.exclusive():
        arm = engine._next_arm()
        a, directory = engine._prepare_attempt(arm, engine._candidate(arm))
    atomic_json(directory / "process.json", {"pid": os.getpid()})
    with pytest.raises(ValueError, match="active"):
        engine.abandon_pending(a["id"], "not safe to abandon")


def test_completed_proposal_is_recovered_without_paid_retry(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)

    def crash(*_):
        raise SystemExit("response persisted but not validated")

    engine._finish_proposal = crash
    with pytest.raises(SystemExit):
        engine.run()
    assert len(proposer.calls) == 1
    engine = reload(engine, robot, proposer)
    engine.run(max_new_attempts=1)
    assert len(proposer.calls) == 1
    assert engine.state["proposals"][0]["status"] == "READY"
    assert any(a["candidate"].get("proposal_id") for a in engine.state["attempts"])


def test_unknown_api_call_stops_without_fallback_or_resend(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)
    calls = []

    def uncertain(*_, **__):
        calls.append(1)
        raise RuntimeError("transport uncertain")

    engine.proposer = uncertain
    with pytest.raises(NeedsAttention):
        engine.run()
    prior = len(robot.calls)
    engine = reload(engine, robot, uncertain)
    with pytest.raises(NeedsAttention, match="will not resend"):
        engine.run()
    assert len(calls) == 1
    assert len(robot.calls) == prior
    assert engine.summary()["afs_requests_without_usage"] == 1
    engine.abandon_pending("proposal_00000", "request no longer active; cost unknown")
    engine = reload(engine, robot, proposer)
    engine.run()
    assert engine.summary()["status"] == "COMPLETE"
    assert engine.summary()["afs_requests_attempted"] == 1 + len(proposer.calls)


@pytest.mark.parametrize("fault", ["refusal", "incomplete", "stale", "extra_robot_field"])
def test_bad_proposals_do_not_launch_or_silently_fallback(tmp_path, fault):
    engine, robot, proposer = setup(tmp_path)
    engine.run(max_new_attempts=4)

    def bad(body, **kwargs):
        response = proposer(body, **kwargs)
        if fault == "refusal":
            response["output"][0]["content"] = [{"type": "refusal", "refusal": "no"}]
        elif fault == "incomplete":
            response["status"] = "incomplete"
        else:
            raw = json.loads(response["output"][0]["content"][0]["text"])
            if fault == "stale":
                raw["context_sha256"] = "wrong"
            else:
                raw["max_calls"] = 999
            response["output"][0]["content"][0]["text"] = json.dumps(raw)
        return response

    engine.proposer = bad
    with pytest.raises(NeedsAttention):
        engine.run()
    assert len(robot.calls) <= 5  # scheduler may execute the other arm before this AFS slot
    assert engine.summary()["afs_requests_attempted"] == 1
    assert engine.summary()["afs_requests_without_usage"] == 0
    assert (engine.root / "proposals/proposal_00000/error.json").exists()


def test_invalid_attempts_do_not_consume_valid_budget_and_attempt_cap(tmp_path):
    engine, _, _ = setup(
        tmp_path,
        config=CampaignConfig(valid_budget_per_seed=2, cold_start=1, max_attempts_per_arm=2),
    )

    def incomplete(_, directory, __):
        (directory / "rollout").mkdir()
        return {"returncode": 1, "wall_s": 0.1, "interrupted": None}

    engine.runner = incomplete
    summary = engine.run()
    assert summary["status"] == "INCOMPLETE"
    assert summary["excluded"] == 4
    assert all(a["valid"] == 0 for a in summary["arms"])
    report = engine.report()
    assert read_json(report.parent / "metrics.json")["comparison"]["status"] == "not_comparable"


def test_watchdog_is_inconclusive_and_stops_invocation(tmp_path):
    engine, robot, _ = setup(tmp_path)

    def timeout(config, directory, params):
        receipt = robot(config, directory, params)
        receipt["interrupted"] = "TimeoutExpired"
        return receipt

    engine.runner = timeout
    result = engine.run()
    assert len(robot.calls) == 1
    assert result["status"] == "READY"
    assert engine.records()[0].status == "INCONCLUSIVE"


def test_code_drift_blocks_before_any_execution(tmp_path):
    engine, robot, _ = setup(tmp_path)
    engine.fingerprint = lambda _: {"different": True}
    with pytest.raises(NeedsAttention, match="drift"):
        engine.run()
    assert not robot.calls


def test_protocol_edit_is_rejected(tmp_path):
    engine, _, _ = setup(tmp_path)
    lock = read_json(engine.root / "protocol.json")
    lock["lock"]["config"]["valid_budget_per_seed"] = 999
    atomic_json(engine.root / "protocol.json", lock)
    with pytest.raises(ValueError, match="protocol mismatch"):
        ResearchCampaign(engine.root)


def test_condition_drift_is_preserved_and_stops_comparison(tmp_path):
    engine, robot, _ = setup(tmp_path)

    def drift(config, directory, params):
        receipt = robot(config, directory, params)
        if len(robot.calls) == 2:
            root = directory / "rollout"
            p = read_json(root / "protocol.json")
            p["source_hashes"]["runner"] = "a" * 64
            json_write(root / "protocol.json", p)
            _rebind(root)
        return receipt

    engine.runner = drift
    assert engine.run()["status"] == "INCOMPLETE"
    assert len(engine.records()) == 2
    assert all(r.status == "VALID" for r in engine.records())
    engine.run()
    assert len(robot.calls) == 2
    report = engine.report()
    assert read_json(report.parent / "metrics.json")["comparison"]["status"] == "not_comparable"


def test_candidate_mismatch_is_not_goal_failure(tmp_path):
    engine, robot, _ = setup(tmp_path)

    def wrong(config, directory, params):
        return robot(config, directory, {**params, "box_mass_kg": 0.5})

    engine.runner = wrong
    assert engine.run()["status"] == "INCOMPLETE"
    assert engine.records()[0].exclusion_reason == "campaign_contract_mismatch"
    assert engine.state["attempts"][0]["raw_episode"]["task_outcome"] == "PASS"


def test_duplicate_evidence_is_excluded_and_not_counted_twice(tmp_path):
    engine, robot, _ = setup(tmp_path)
    engine.run(max_new_attempts=1)
    first = engine.root / "attempts/attempt_00000/rollout"

    def duplicate(_, directory, __):
        shutil.copytree(first, directory / "rollout")
        return {"returncode": 0, "wall_s": 0.1, "interrupted": None}

    engine.runner = duplicate
    engine.run(max_new_attempts=1)
    assert len([r for r in engine.records() if r.status == "VALID"]) == 1
    assert engine.records()[-1].exclusion_reason == "duplicate_core_evidence"


def test_feedback_uses_only_own_arm_and_has_time_evidence(tmp_path):
    engine, _, proposer = setup(tmp_path)
    engine.run()
    for row in engine.state["proposals"]:
        ctx = row["context"]
        evidence = [e for e in ctx["latest"]["evidence"] if "outcome" in e]
        own = {r.evidence_id for r in engine.records("afs", row["seed"])}
        assert {e["id"] for e in evidence} <= own
        assert ctx["history_selection"]["other_arm_data_used"] is False
        assert all("intervals" in e and "object_motion" in e for e in evidence)
        request = row["request"]
        assert request["store"] is False
        fmt = request["text"]["format"]
        assert fmt["strict"] is True
        assert fmt["schema"]["properties"]["context_sha256"]["enum"] == [digest(ctx)]
    assert len(proposer.calls) == len(engine.state["proposals"])


def test_observed_bracket_and_mixed_repeats(tmp_path):
    a = fixture(tmp_path / "a", outcome="PASS", mass=1.0)
    b = fixture(tmp_path / "b", mass=3.0)
    memory = build_failure_memory([load(a), load(b)])
    candidate = boundary_candidate(memory)
    assert candidate["parameters"]["box_mass_kg"] == 2.0
    assert candidate["stage"] == "boundary"
    c = fixture(tmp_path / "c", outcome="PASS", mass=3.0)
    assert boundary_candidate(build_failure_memory([load(a), load(b), load(c)])) is None


def test_llm_space_changes_selected_environment_and_schema_is_strict(tmp_path):
    memory = build_failure_memory([load(fixture(tmp_path / "anchor"))])
    ctx = feedback_context(memory, history_limit=2, remaining=6)
    body = proposal_request(ctx, "gpt-6-astra")
    response = FakeProposer()(body)
    raw = json.loads(response["output"][0]["content"][0]["text"])
    first = choose_probe(raw, ctx, memory)
    raw["spaces"][0].update(axis="floor_friction", low=0.06, high=1.4)
    second = choose_probe(raw, ctx, memory)
    assert first["parameters"] != second["parameters"]
    assert second["parameters"]["box_mass_kg"] == 2.0
    assert first["parameters"]["floor_friction"] == 0.8
    schema = body["text"]["format"]["schema"]
    for obj in [schema, *schema["$defs"].values()]:
        assert obj["additionalProperties"] is False
        assert set(obj["properties"]) == set(obj["required"])
    raw["spaces"][0]["evidence_refs"] = ["invented"]
    with pytest.raises(ValueError, match="unknown evidence"):
        choose_probe(raw, ctx, memory)


def test_request_cap_is_bounded_and_not_a_random_fallback(tmp_path):
    config = CampaignConfig(
        robot=RobotSettings(model="synthetic-mock"),
        max_proposals_per_seed=1,
        strategy_cycle=["boundary", "llm", "exploration", "repeat"],
    )
    engine, _, proposer = setup(tmp_path, config=config)
    with pytest.raises(NeedsAttention, match="request cap"):
        engine.run()
    assert len(proposer.calls) == 1
    assert engine.summary()["status"] == "INCOMPLETE"


def test_multiple_seeds_have_independent_feedback_and_budgets(tmp_path):
    config = CampaignConfig(
        robot=RobotSettings(model="synthetic-mock"),
        seeds=[3, 17],
        valid_budget_per_seed=4,
        cold_start=1,
    )
    engine, _, _ = setup(tmp_path, config=config)
    summary = engine.run()
    assert summary["status"] == "COMPLETE"
    assert [a["valid"] for a in summary["arms"]] == [4, 4, 4, 4]
    for p in engine.state["proposals"]:
        allowed = {r.evidence_id for r in engine.records("afs", p["seed"])}
        actual = {e["id"] for e in p["context"]["latest"]["evidence"] if "outcome" in e}
        assert actual <= allowed


def test_completed_evidence_changes_block_feedback_and_report(tmp_path):
    engine, _, _ = setup(tmp_path)
    engine.run(max_new_attempts=4)
    record = engine.records("afs", 17)[0]
    (Path(record.source.path) / "scene.xml").write_text("<changed/>")
    with pytest.raises(NeedsAttention, match="evidence changed"):
        engine._memory(17)
    with pytest.raises(NeedsAttention, match="evidence changed"):
        engine.report()


def test_live_child_blocks_resume_even_if_manifest_exists(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    with engine.store.exclusive():
        arm = engine._next_arm()
        a, directory = engine._prepare_attempt(arm, engine._candidate(arm))
    robot(engine.config, directory, a["candidate"]["parameters"])
    atomic_json(directory / "process.json", {"pid": os.getpid()})
    other = reload(engine, robot, proposer)
    with pytest.raises(NeedsAttention, match="still be active"):
        other.run()
    assert len(robot.calls) == 1


def test_method_checkpoint_observe_idempotent_but_not_conflicting():
    method = BehaviorMethodState()
    obs = CandidateObservation(candidate_id="one", status="EVALUATED", failure=True)
    method.observe([obs, obs])
    restored = BehaviorMethodState(method.state_dict())
    assert len(restored.observed) == 1
    with pytest.raises(ValueError, match="conflicting"):
        restored.observe([obs.model_copy(update={"failure": False})])


def test_exclusive_lock_blocks_second_driver(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    other = reload(engine, robot, proposer)
    with engine.store.exclusive():
        with pytest.raises(RuntimeError, match="another process"):
            other.run()
    assert not robot.calls


def test_errors_redact_secrets(tmp_path, monkeypatch):
    engine, _, _ = setup(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "test-credential-only")

    def broken(*_):
        raise RuntimeError("test-credential-only Bearer other-token")

    engine.runner = broken
    with pytest.raises(RuntimeError):
        engine.run()
    saved = (engine.root / "last_error.json").read_text()
    assert "test-credential-only" not in saved and "other-token" not in saved
    assert "[REDACTED]" in saved


def test_command_preserves_unlimited_time_and_separates_watchdog(tmp_path):
    config = CampaignConfig(robot=RobotSettings(watchdog_wall_s=5000.0))
    args = command(config, tmp_path / "scene.json", tmp_path / "run")
    assert "--max-seconds" not in args
    assert "--run-dir" in args and "--live" in args and "--enable-push" in args
    assert "5000" not in str(args)


@pytest.mark.parametrize("watchdog", [False, True])
def test_subprocess_adapter_receipts_and_no_implicit_retry(tmp_path, monkeypatch, watchdog):
    import failure_client.experiments.local_goal_adapter as adapter

    calls, signals = [], []

    class Process:
        pid = 999999999
        returncode = -15 if watchdog else 0

        def wait(self, timeout=None):
            if watchdog and timeout == 5000:
                raise subprocess.TimeoutExpired("synthetic command", timeout)
            return self.returncode

    def launch(argv, **kwargs):
        calls.append((argv, kwargs))
        return Process()

    monkeypatch.setattr(adapter.subprocess, "Popen", launch)
    monkeypatch.setattr(adapter.os, "killpg", lambda *args: signals.append(args))
    config = CampaignConfig(robot=RobotSettings(watchdog_wall_s=5000.0))
    receipt = LocalGoalRunner()(config, tmp_path, uniform_scene(17, "adapter"))
    assert len(calls) == 1
    assert calls[0][1]["start_new_session"] is True
    assert receipt["interrupted"] == ("TimeoutExpired" if watchdog else None)
    assert bool(signals) is watchdog
    assert read_json(tmp_path / "receipt.json") == receipt
    assert read_json(tmp_path / "scene_config.json")["schema_version"] == "clear-path-fixture-v1"
    (tmp_path / "rollout").mkdir()
    with pytest.raises(ValueError, match="existing rollout"):
        LocalGoalRunner()(config, tmp_path, uniform_scene(17, "adapter"))
    assert len(calls) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"seeds": [1, 1]},
        {"seeds": [-1]},
        {"cold_start": 8},
        {"max_attempts_per_arm": 2},
        {"strategy_cycle": ["llm"]},
        {"robot": {"max_seconds": 1.0}},
        {"robot": {"groot_root": "relative"}},
    ],
)
def test_invalid_config(changes):
    with pytest.raises(ValueError):
        CampaignConfig.model_validate(changes)


def test_cli_cannot_accidentally_launch_without_live_or_key(tmp_path):
    tool = Path(__file__).resolve().parents[2] / "tools/run_afs_benchmark.py"
    process = subprocess.run(
        [sys.executable, str(tool), "run", "--campaign", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert process.returncode == 2
    assert "requires --live" in process.stderr
    assert not list(tmp_path.iterdir())
