"""Synthetic contrasts: no remote inference or GPU success claims."""

import copy
import json
import runpy
from pathlib import Path

import pytest

from failure_client.evaluation.goal_run_reader import read_json
from failure_client.experiments.afs_contrast import (
    contrast_plan,
    evidence,
    next_request,
    next_selection,
    selected_plan,
    validate_plan,
)
from failure_client.experiments.behavior_regression import BehaviorRegression
from failure_client.experiments.local_goal_adapter import atomic_json, command
from robot_vlm.navigation_completion import completion_contract

from .test_behavior_memory import _rebind
from .test_corridor_campaign import CorridorProposer, archive
from .test_discovery_measures import json_write


def source(root, **kwargs):
    root = archive(root, **kwargs)
    p = read_json(root / "protocol.json")
    p["navigation_completion"] = completion_contract("goal_dwell_v1")
    json_write(root / "protocol.json", p)
    rows = [json.loads(s) for s in (root / "decisions.jsonl").read_text().splitlines()]
    for row in rows:
        if "provider" in row:
            row["provider"]["request_id"] = str(root)
    (root / "decisions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    _rebind(root)
    return root


def fingerprint(_):
    return {
        "source_hashes": {"runner": "f" * 64},
        "robot_resources": {"robot.xml": "f" * 64},
        "runtime_versions": {},
    }


class Robot:
    def __init__(self, *, crash=False, drift=False, excluded=False):
        self.calls = []
        self.crash, self.drift, self.excluded = crash, drift, excluded

    def __call__(self, cfg, directory, params):
        directory.mkdir(parents=True)
        self.calls.append(params)
        root = source(
            directory / "rollout",
            scene=cfg.scene(params),
            outcome="PASS" if params["corridor_width_m"] >= 3 else "FAIL",
        )
        if self.drift:
            p = read_json(root / "protocol.json")
            p["source_hashes"]["runner"] = "d" * 64
            json_write(root / "protocol.json", p)
            _rebind(root)
        receipt = {
            "returncode": 0,
            "wall_s": 0.1,
            "interrupted": "external" if self.excluded else None,
        }
        atomic_json(directory / "receipt.json", receipt)
        if self.crash:
            raise RuntimeError("crash after completed archive")
        return receipt


def setup(tmp_path, *, robot=None):
    baseline = source(tmp_path / "baseline")
    plan = contrast_plan([baseline], axis="corridor_width_m", values=[3.2, 2.4])
    root = BehaviorRegression.create(
        tmp_path / "suite", plan, fingerprint=fingerprint, execution_origin="mock"
    )
    robot = robot or Robot()
    return baseline, BehaviorRegression(root, runner=robot, fingerprint=fingerprint), robot


def test_plan_changes_one_axis_keeps_goal_robot_and_bounded_budget(tmp_path):
    a, b = source(tmp_path / "a"), source(tmp_path / "b")
    before = sorted(tmp_path.rglob("*"))
    plan = contrast_plan([a, b], axis="corridor_width_m", values=[3.6, 3.2])
    assert sorted(tmp_path.rglob("*")) == before
    assert len(plan["history"]) == 2
    assert plan["max_attempts"] == 3 and plan["robot_api_call_upper_bound"] == 30
    assert plan["afs_requests"] == 0
    assert plan["cases"][0]["baseline_pass"] == 2
    assert plan["selection"]["origin"] == "operator_selected_contrast"
    for c in plan["cases"]:
        original = plan["reference_scene"]
        assert all(v == c["scene"][k] for k, v in original.items() if k != plan["axis"])
        cfg = c["target_config"]["robot"]
        assert cfg["max_calls"] == 10 and cfg["max_seconds"] is None
        assert cfg["navigation_completion"] == "goal_dwell_v1"
    assert not list(tmp_path.rglob("campaign.sqlite3"))


@pytest.mark.parametrize("values", [[4.0], [3.2, 3.2], [0.5], [float("nan")], [float("inf")]])
def test_invalid_probe_values_rejected(tmp_path, values):
    baseline = source(tmp_path / "baseline")
    with pytest.raises(ValueError):
        contrast_plan([baseline], axis="corridor_width_m", values=values)


def test_other_axis_and_robot_changes_refused(tmp_path):
    baseline = source(tmp_path / "baseline")
    plan = contrast_plan([baseline], axis="corridor_width_m", values=[3.2])
    changed = copy.deepcopy(plan)
    changed["cases"][1]["scene"]["box_mass_kg"] += 1
    with pytest.raises(ValueError, match="every other"):
        validate_plan(changed)
    changed = copy.deepcopy(plan)
    for c in changed["cases"]:
        c["target_config"]["robot"]["max_calls"] = 20
    with pytest.raises(ValueError, match="override"):
        validate_plan(changed)
    with pytest.raises(ValueError, match="code/resources"):
        BehaviorRegression.create(
            tmp_path / "bad",
            plan,
            execution_origin="mock",
            fingerprint=lambda _: {**fingerprint(None), "source_hashes": {}},
        )
    assert not (tmp_path / "bad").exists()


def test_different_robot_conditions_and_unaudited_geometry_rejected(tmp_path):
    a, b = source(tmp_path / "a"), source(tmp_path / "b")
    p = read_json(b / "protocol.json")
    p["source_hashes"]["runner"] = "d" * 64
    json_write(b / "protocol.json", p)
    _rebind(b)
    with pytest.raises(ValueError, match="one verified"):
        evidence([a, b])
    (a / "scene.xml").write_text("<mujoco/>")
    _rebind(a)
    with pytest.raises(ValueError):
        evidence([a])


def test_run_resume_report_midpoint_and_originals_preserved(tmp_path):
    baseline, suite, robot = setup(tmp_path)
    original = (baseline / "manifest.json").read_bytes()
    with pytest.raises(ValueError, match="live"):
        suite.run()
    suite.run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 1
    suite.run(live=True)
    assert len(robot.calls) == 3 and suite.summary()["status"] == "COMPLETE"
    assert [c["comparison"] for c in suite.summary()["cases"]] == [
        "OBSERVED_PASS",
        "OBSERVED_PASS",
        "OBSERVED_FAIL",
    ]
    suite.run(live=True)
    assert len(robot.calls) == 3
    paths = [baseline] + [suite._directory(a) / "rollout" for a in suite.state["attempts"]]
    memory, candidate, ctx, body = next_request(paths)
    assert body is ctx is None
    assert candidate["parameters"]["corridor_width_m"] == 2.8
    assert candidate["strategy"] == "observed_boundary_midpoint"
    next_plan = selected_plan(paths, candidate)
    assert next_plan["max_attempts"] == 2
    assert next_plan["reference_scene"]["corridor_width_m"] == 2.4
    report = suite.report()
    assert (report.parent / "behavior/index.html").is_file()
    assert "AFS/Random" in report.read_text()
    assert len(read_json(report.parent / "behavior/memory.json")["brackets"]) == 1
    for p in (report.parent / "behavior/cases").glob("*/REPRODUCE.txt"):
        assert "--navigation-completion goal_dwell_v1" in p.read_text()
    assert not list(report.parent.rglob("*.gif"))
    assert (baseline / "manifest.json").read_bytes() == original


def test_mixed_repeats_precede_boundary_and_all_fail_never_invents_bracket(tmp_path):
    a = source(tmp_path / "a", width=4)
    b = source(tmp_path / "b", width=4, outcome="FAIL")
    c = source(tmp_path / "c", width=2.4, outcome="FAIL")
    m, candidate, ctx, body = next_request([a, b, c])
    assert candidate["strategy"] == "mixed_outcome_repeat" and body is None
    plan = selected_plan([a, b, c], candidate)
    assert plan["max_attempts"] == 1 and plan["cases"][0]["baseline_fail"] == 1
    m, candidate, ctx, body = next_request([c])
    assert candidate is None and not m["brackets"]
    assert ctx["search_selection"]["state"] == "no_success_control"
    assert body["model"] == "gpt-6-luna" and "max_output_tokens" not in body


def test_llm_selection_reuses_strict_context_and_retains_single_axis(tmp_path):
    from llm_afs.provider import extract_proposal

    a = source(tmp_path / "a")
    memory, candidate, ctx, body = next_request([a])
    assert candidate is None
    raw = extract_proposal(CorridorProposer()(body))
    candidate, _ = next_selection(memory, raw=raw)
    plan = selected_plan([a], candidate)
    assert plan["axis"] == "corridor_width_m" and plan["max_attempts"] == 2
    raw["context_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="stale"):
        next_selection(memory, raw=raw)


def test_crash_recovers_without_resend_and_drift_excludes(tmp_path):
    _, suite, robot = setup(tmp_path, robot=Robot(crash=True))
    with pytest.raises(RuntimeError):
        suite.run(live=True)
    suite.run(live=True, max_new_attempts=0)
    assert len(robot.calls) == 1 and suite.state["pending"] is None
    robot.crash, robot.drift = False, True
    suite.run(live=True)
    assert len(robot.calls) == 2
    assert suite.summary()["status"] == "NEEDS_ATTENTION"
    assert (
        suite.state["attempts"][-1]["episode"]["exclusion_reason"]
        == "contrast_condition_or_returned_model_drift"
    )


def test_cli_plan_is_offline_and_preserves_completion_in_command(tmp_path, capsys):
    baseline = source(tmp_path / "baseline")
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/run_afs_contrast.py"))[
        "main"
    ]
    assert (
        main(["plan", "--run", str(baseline), "--axis", "corridor_width_m", "--values", "3.2"]) == 0
    )
    assert '"robot_api_call_upper_bound": 20' in capsys.readouterr().out
    assert not list(tmp_path.rglob("campaign.sqlite3"))
    from failure_client.experiments.research_protocol import CampaignConfig

    plan = contrast_plan([baseline], axis="corridor_width_m", values=[3.2])
    args = command(CampaignConfig.model_validate(plan["cases"][0]["target_config"]), "scene", "out")
    assert args[args.index("--navigation-completion") + 1] == "goal_dwell_v1"


@pytest.mark.parametrize("live", [False, True])
def test_cli_next_prepares_or_calls_once_without_robot(tmp_path, monkeypatch, live):
    from failure_client.experiments import behavior_regression
    from llm_afs import provider

    monkeypatch.setattr(behavior_regression, "regression_fingerprint", fingerprint)
    baseline = source(tmp_path / "baseline")
    plan = contrast_plan([baseline], axis="corridor_width_m", values=[3.2])
    root = BehaviorRegression.create(tmp_path / "suite", plan, execution_origin="mock")
    robot = Robot()
    suite = BehaviorRegression(root, runner=robot)
    suite.run(live=True)
    proposer = CorridorProposer()
    monkeypatch.setattr(provider, "call", proposer)
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/run_afs_contrast.py"))[
        "main"
    ]
    output = tmp_path / "next"
    args = ["next", "--suite", str(root), "--output-dir", str(output)]
    assert main(args + (["--live"] if live else [])) == 0
    assert len(proposer.calls) == int(live) and len(robot.calls) == 2
    request = read_json(output / "request.json")
    assert "anchored-contrast-endpoint-v1" in request["instructions"]
    assert "No automatic exploration slot" in request["instructions"]
    assert "campaign-hypothesis-endpoint-v2" not in request["instructions"]
    assert request["model"] == "gpt-6-luna"
    if live:
        created = BehaviorRegression(output / "suite")
        assert created.summary()["status"] == "READY"
        assert created.state["attempts"] == []
        assert created.summary()["selection_costs"][0]["usage"]["input_tokens"] == 12
        assert (output / "suite/preview/index.html").exists()
        # A saved response can be validated again without another paid call.
        reused = tmp_path / "reused"
        assert (
            main(
                [
                    "next",
                    "--suite",
                    str(root),
                    "--output-dir",
                    str(reused),
                    "--response",
                    str(output / "response.json"),
                ]
            )
            == 0
        )
        assert len(proposer.calls) == 1
    else:
        assert not (output / "suite").exists()


def test_cli_bad_response_stops_and_keeps_cost_and_evidence(tmp_path, monkeypatch):
    from failure_client.experiments import behavior_regression
    from llm_afs import provider

    monkeypatch.setattr(behavior_regression, "regression_fingerprint", fingerprint)
    _, suite, robot = setup(tmp_path)
    # Execute just the control, then reject next before any request.
    suite.run(live=True, max_new_attempts=1)
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/run_afs_contrast.py"))[
        "main"
    ]
    calls = []

    def bad(body, **_):
        calls.append(body)
        return {"status": "incomplete", "usage": {"input_tokens": 10}}

    monkeypatch.setattr(provider, "call", bad)
    with pytest.raises(SystemExit):
        main(["next", "--suite", str(suite.root), "--live"])
    assert calls == []
    # Complete an all-PASS suite to require an LLM hypothesis.
    baseline = source(tmp_path / "another")
    plan = contrast_plan([baseline], axis="corridor_width_m", values=[3.2])
    root = BehaviorRegression.create(tmp_path / "allpass", plan, execution_origin="mock")
    BehaviorRegression(root, runner=Robot()).run(live=True)
    output = tmp_path / "bad_response"
    with pytest.raises(SystemExit):
        main(["next", "--suite", str(root), "--live", "--output-dir", str(output)])
    assert len(calls) == 1
    assert (output / "intent.json").exists() and (output / "error.json").exists()
    assert read_json(output / "usage.json")["usage"]["input_tokens"] == 10
    assert not (output / "suite").exists()
