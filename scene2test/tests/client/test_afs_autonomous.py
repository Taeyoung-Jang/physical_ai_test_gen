"""Synthetic state-machine checks; not G1 physics or live model validation."""

import copy
import json
import os
import runpy
from pathlib import Path

import pytest
from jsonschema import validate

from clear_path.contracts import GoalRegionFixture
from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.afs_autonomous import AutonomousAFS, development_plan
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe, selection
from llm_afs.behavior_request import request

from .test_afs_contrast import Robot, fingerprint, source


class Proposer:
    def __init__(self):
        self.calls = []

    def __call__(self, body, **_):
        self.calls.append(copy.deepcopy(body))
        payload = json.loads(body["input"][0]["content"])
        ctx = payload["context"]
        axis = ctx["development_search"]["selectable_axes"][0]
        low, high = ctx["allowed_axes"][axis]
        # Novel endpoints even when an earlier same-axis sample used a domain edge.
        delta = (high - low) * 0.013 * len(self.calls)
        raw = {
            "context_sha256": payload["context_sha256"],
            "spaces": [
                {
                    "mode": "cross_mechanism",
                    "axis": axis,
                    "low": low + delta,
                    "high": high - delta,
                    "evidence_refs": ["case_memory"],
                    "hypothesis": "synthetic alternative",
                    "alternative": "stochastic variation",
                    "falsification": "opposite observed outcome",
                }
            ],
        }
        validate(raw, body["text"]["format"]["schema"])
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 123, "output_tokens": 45},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        }


def setup(tmp_path, *, budget=None, robot=None, proposer=None, v4=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    args = {"scene": GoalRegionFixture()} if v4 else {}
    a = source(tmp_path / "base_pass", outcome="PASS", **args)
    b = source(tmp_path / "base_fail", outcome="FAIL", **args)
    root = AutonomousAFS.create(tmp_path / "session", [a, b], budget, fingerprint_fn=fingerprint)
    robot, proposer = robot or Robot(), proposer or Proposer()
    return (
        AutonomousAFS(root, runner=robot, proposer=proposer, fingerprint_fn=fingerprint),
        robot,
        proposer,
    )


def reload(engine, robot, proposer):
    return AutonomousAFS(engine.root, runner=robot, proposer=proposer, fingerprint_fn=fingerprint)


def test_bounded_loop_mixed_repeat_axis_diversity_and_report(tmp_path):
    engine, robot, proposer = setup(tmp_path, v4=True)
    hashes = [(r["source"]["path"], r["artifact_hashes"]) for r in engine.plan["history"]]
    summary = engine.run(live=True)
    assert summary["status"] == "COMPLETE"
    assert len(robot.calls) == 6
    assert len(proposer.calls) <= 6
    assert summary["scheduler"]["repeats"] == 1
    axes = [a["candidate"]["axis"] for a in engine.state["attempts"] if a["candidate"]["axis"]]
    assert all(a != b for a, b in zip(axes, axes[1:]))
    assert all(count <= 2 for count in summary["scheduler"]["axis_attempts"].values())
    assert len(set(axes)) >= 3
    assert (
        len(json.loads(proposer.calls[0]["input"][0]["content"])["context"]["allowed_axes"]) == 18
    )
    assert all("max_output_tokens" not in body for body in proposer.calls)
    assert all("action_timeline" in json.dumps(body) for body in proposer.calls)
    report = engine.report()
    assert report.is_file()
    assert (report.parent / "behavior/memory.json").is_file()
    assert read_json(report.parent / "search_diagnostics.json")["new_execution_only"]["groups"]
    assert read_json(report.parent / "hypothesis_reviews.json")
    assert "AFS/Random" in report.read_text()
    assert summary["inherited_history_costs"]["robot_api_calls"]["missing_attempts"] == 0
    for path, manifest in hashes:
        from failure_client.evaluation.goal_run_reader import read_goal_run
        from failure_client.evaluation.research_records import RunInput

        assert read_goal_run(RunInput(path=path)).artifact_hashes == manifest
    before = len(robot.calls), len(proposer.calls)
    assert reload(engine, robot, proposer).run(live=True)["status"] == "COMPLETE"
    assert before == (len(robot.calls), len(proposer.calls))


def test_resume_fixed_total_budget(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    for _ in range(6):
        engine = reload(engine, robot, proposer)
        engine.run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 6
    assert engine.summary()["status"] == "COMPLETE"
    assert engine.summary()["afs_requests_attempted"] == len(proposer.calls)


def test_crash_after_archive_collect_without_redispatch(tmp_path):
    engine, robot, proposer = setup(tmp_path, robot=Robot(crash=True))
    with pytest.raises(RuntimeError, match="crash after"):
        engine.run(live=True)
    resumed = reload(engine, robot, proposer)
    summary = resumed.run(live=True, max_new_attempts=0)
    assert summary["pending"] is None and summary["attempted"] == 1
    assert len(robot.calls) == len(proposer.calls) == 1
    assert list((engine.root / "errors").glob("*.json"))


def test_crash_after_saved_response_recovers_without_second_call(tmp_path, monkeypatch):
    engine, robot, proposer = setup(tmp_path)

    def crash(_):
        raise RuntimeError("after response saved")

    monkeypatch.setattr(engine, "_finish_proposal", crash)
    with pytest.raises(RuntimeError, match="after response"):
        engine.run(live=True)
    assert len(proposer.calls) == 1 and not robot.calls
    resumed = reload(engine, robot, proposer)
    resumed.run(live=True, max_new_attempts=1)
    assert len(proposer.calls) == len(robot.calls) == 1
    assert resumed.summary()["selection_costs"]["input_tokens"]["observed"] == 123


def test_timeout_unknown_cost_never_resend_and_secret_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")
    calls = []

    def timeout(*args, **kwargs):
        calls.append(1)
        raise TimeoutError("synthetic-secret Bearer abc")

    engine, robot, _ = setup(tmp_path, proposer=timeout)
    with pytest.raises(TimeoutError):
        engine.run(live=True)
    with pytest.raises(RuntimeError, match="never resend"):
        reload(engine, robot, timeout).run(live=True)
    assert len(calls) == 1 and not robot.calls
    summary = engine.summary()
    assert summary["selection_costs"]["input_tokens"] == {"observed": None, "missing_requests": 1}
    assert "synthetic-secret" not in "".join(
        p.read_text() for p in (engine.root / "errors").glob("*.json")
    )


def test_ambiguous_robot_no_resend_and_active_process_guard(tmp_path):
    calls = []

    def crash(cfg, directory, params):
        calls.append(1)
        atomic_json(directory / "process.json", {"pid": os.getpid()})
        raise RuntimeError("dispatch interrupted")

    engine, _, proposer = setup(tmp_path, robot=crash)
    with pytest.raises(RuntimeError):
        engine.run(live=True)
    with pytest.raises(RuntimeError, match="may still be active"):
        reload(engine, crash, proposer).run(live=True)
    assert len(calls) == len(proposer.calls) == 1


@pytest.mark.parametrize("mode", ["drift", "excluded"])
def test_exclusion_stops_consumes_budget_and_never_guides_search(tmp_path, mode):
    engine, robot, proposer = setup(tmp_path, robot=Robot(**{mode: True}))
    result = engine.run(live=True)
    assert result["status"] == "NEEDS_ATTENTION" and result["excluded"] == 1
    assert len(robot.calls) == 1
    memory = engine._memory()
    assert len(memory["episodes"]) == 2 and len(memory["excluded"]) == 1
    assert engine.state["attempts"][0]["raw_episode"]["status"] == "VALID"
    reload(engine, robot, proposer).run(live=True)
    assert len(robot.calls) == 1
    robot.drift = robot.excluded = False
    resumed = reload(engine, robot, proposer)
    resumed.run(live=True, max_new_attempts=1, continue_after_exclusion=True)
    assert len(robot.calls) == 2 and resumed.summary()["excluded"] == 1


def test_afs_budget_and_axis_quotas_do_not_silently_fallback(tmp_path):
    engine, robot, proposer = setup(
        tmp_path, budget=SearchBudget(max_afs_requests=1, max_repeats=0)
    )
    result = engine.run(live=True)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["reason"] == "afs_request_budget"
    assert len(robot.calls) == len(proposer.calls) == 1


def test_host_enforces_cooldown_even_if_provider_ignores_schema(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(live=True, max_new_attempts=2)
    memory = engine._memory()
    _, ctx = selection(memory, engine.state["attempts"], engine.budget, engine.cfg.scene_schema)
    body = request(ctx, "synthetic-mock", selection_policy="autonomous_development_endpoint")
    raw = json.loads(proposer(body)["output"][0]["content"][0]["text"])
    blocked = next(iter(ctx["development_search"]["blocked_axes"]))
    raw["spaces"][0].update(
        axis=blocked,
        low=float(ctx["allowed_axes"][blocked][0]),
        high=float(ctx["allowed_axes"][blocked][1]),
    )
    with pytest.raises(ValueError, match="cooled-down"):
        selected_probe(raw, ctx, memory)


def test_invalid_schema_preserves_usage_stops_and_never_launches(tmp_path):
    underlying = Proposer()

    def broken(body, **kwargs):
        response = underlying(body)
        response["output"][0]["content"][0]["text"] = "{}"
        return response

    engine, robot, _ = setup(tmp_path, proposer=broken)
    for _ in range(2):
        with pytest.raises(ValueError):
            engine.run(live=True)
    assert len(underlying.calls) == 1 and not robot.calls
    assert engine.summary()["selection_costs"]["input_tokens"]["observed"] == 123


def test_environment_evidence_and_lock_tamper_block_before_dispatch(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.fingerprint = lambda _: {"changed": True}
    with pytest.raises(ValueError, match="frozen source"):
        engine.run(live=True)
    assert not robot.calls and not proposer.calls
    engine = reload(engine, robot, proposer)
    original = read_json(engine.root / "protocol.json")
    original["lock"]["plan"]["budget"]["max_attempts"] = 99
    atomic_json(engine.root / "protocol.json", original)
    with pytest.raises(ValueError, match="session protocol"):
        reload(engine, robot, proposer)


def test_live_opt_in_lock_and_read_only_plan(tmp_path):
    a = source(tmp_path / "a")
    before = sorted(tmp_path.rglob("*"))
    plan = development_plan([a], fingerprint_fn=fingerprint)
    assert sorted(tmp_path.rglob("*")) == before
    assert plan["plan"]["robot_api_call_upper_bound"] == 60
    engine, robot, proposer = setup(tmp_path / "other")
    with pytest.raises(ValueError, match="live"):
        engine.run()
    with engine.store.exclusive():
        with pytest.raises(RuntimeError, match="another process"):
            reload(engine, robot, proposer).run(live=True)
    assert not robot.calls and not proposer.calls


def test_cli_rejects_resume_overrides_and_requires_live(tmp_path):
    main = runpy.run_path(str(Path(__file__).parents[2] / "tools/run_afs_autonomous.py"))["main"]
    with pytest.raises(SystemExit):
        main(["run", "--session", str(tmp_path), "--config", "anything.json", "--live"])
    with pytest.raises(SystemExit):
        main(["run", "--session", str(tmp_path)])


def test_llm_first_even_with_bracket_then_bounded_midpoint(tmp_path):
    from failure_client.experiments.afs_contrast import evidence

    a = source(tmp_path / "pass", width=4.0, outcome="PASS")
    b = source(tmp_path / "fail", width=2.4, outcome="FAIL")
    memory = evidence([a, b])
    assert len(memory["brackets"]) == 1
    budget = SearchBudget()
    candidate, ctx = selection(memory, [], budget, "clear-path-corridor-v2")
    assert candidate is None and ctx is not None  # midpoint cannot starve first hypothesis
    prior = [{"candidate": {"axis": "box_mass_kg", "stage": "discovery"}}]
    candidate, ctx = selection(memory, prior, budget, "clear-path-corridor-v2")
    assert ctx is None and candidate["stage"] == "boundary"
    assert candidate["axis"] == "corridor_width_m"
    assert candidate["parameters"]["corridor_width_m"] == 3.2
    # Even an available bracket cannot occupy the next mandatory hypothesis slot.
    candidate, ctx = selection(
        memory, prior + [{"candidate": candidate}], budget, "clear-path-corridor-v2"
    )
    assert candidate is None and ctx is not None
    assert "corridor_width_m" not in ctx["development_search"]["selectable_axes"]


def test_response_artifacts_cannot_change_on_resume(tmp_path):
    engine, robot, proposer = setup(tmp_path)
    engine.run(live=True, max_new_attempts=1)
    response = engine.root / "proposals/proposal_00000/response.json"
    value = read_json(response)
    value["model"] = "edited response"
    atomic_json(response, value)
    with pytest.raises(ValueError, match="selection evidence changed"):
        reload(engine, robot, proposer).run(live=True)
    assert len(robot.calls) == len(proposer.calls) == 1


def test_same_condition_preflight_refuses_robot_source_drift(tmp_path):
    a = source(tmp_path / "a")
    changed = fingerprint(None)
    changed["source_hashes"] = {"runner": "b" * 64}
    with pytest.raises(ValueError, match="robot code/resources/runtime changed"):
        development_plan([a], fingerprint_fn=lambda _: changed)


def test_interrupt_after_selection_resumes_without_second_request(tmp_path):
    engine, robot, proposer = setup(tmp_path)

    def interrupt(event):
        if event["event"] == "proposal_validated":
            raise KeyboardInterrupt()

    engine.on_event = interrupt
    with pytest.raises(KeyboardInterrupt):
        engine.run(live=True)
    assert engine.state["selected"] and not engine.state["pending"]
    assert engine.state["reason"] == "operator_interrupted"
    resumed = reload(engine, robot, proposer)
    resumed.run(live=True, max_new_attempts=1)
    assert len(robot.calls) == len(proposer.calls) == 1


def test_old_suite_is_rejected_before_database_open(tmp_path):
    atomic_json(tmp_path / "protocol.json", {"lock": {"plan": {"mode": "old-suite"}}})
    with pytest.raises(ValueError, match="autonomous session"):
        AutonomousAFS(tmp_path)
    assert not (tmp_path / "campaign.sqlite3").exists()
