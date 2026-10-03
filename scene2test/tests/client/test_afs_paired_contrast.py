"""Synthetic paired AFS selection and durable execution; no paid/GPU runs."""

import copy
import json

import jsonschema
import pytest

from clear_path.contracts import GoalRegionFixture
from failure_client.experiments.afs_contrast import next_request
from failure_client.experiments.afs_paired_contrast import (
    AXIS,
    PairedSelection,
    paired_plan,
    paired_request,
)
from failure_client.experiments.behavior_regression import BehaviorRegression
from failure_client.experiments.local_goal_adapter import atomic_json
from robot_vlm.task_outcome import digest

from .test_afs_contrast import fingerprint, source


def history(tmp_path):
    return [
        source(tmp_path / "clear", scene=GoalRegionFixture(box_lateral_fraction=1.0)),
        source(tmp_path / "partial", scene=GoalRegionFixture(box_lateral_fraction=0.5)),
    ]


def response(body):
    payload = json.loads(body["input"][0]["content"])
    ctx = payload["context"]
    ids = body["text"]["format"]["schema"]["$defs"]["Probe"]["properties"]["evidence_refs"][
        "items"
    ]["enum"]
    raw = {
        "context_sha256": payload["context_sha256"],
        "anchor_case_id": ctx["search_selection"]["anchor_case_id"],
        "axis": AXIS,
        "relief": {
            "value": 0.75,
            "evidence_refs": ids,
            "hypothesis": "More lateral space",
            "expected_observation": "May need fewer fine moves",
            "falsification": "No improvement",
        },
        "challenge": {
            "value": 0.25,
            "evidence_refs": ids,
            "hypothesis": "Less lateral space",
            "expected_observation": "May select a different tool",
            "falsification": "Same behavior",
        },
    }
    jsonschema.validate(raw, body["text"]["format"]["schema"])
    return {
        "status": "completed",
        "model": body["model"],
        "usage": {"input_tokens": 12, "output_tokens": 20},
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": json.dumps(raw)}],
            }
        ],
    }


def proposal(body):
    return json.loads(response(body)["output"][0]["content"][0]["text"])


def prepare(tmp_path):
    paths = history(tmp_path)
    root = PairedSelection.prepare(
        tmp_path / "session", paths, fingerprint=fingerprint, execution_origin="mock"
    )
    return paths, PairedSelection(root, fingerprint=fingerprint)


def test_request_preserves_two_behavior_timelines_and_only_allowed_axis(tmp_path):
    paths = history(tmp_path)
    before = sorted(tmp_path.rglob("*"))
    memory, ctx, body = paired_request(paths)
    assert sorted(tmp_path.rglob("*")) == before
    assert len(memory["episodes"]) == 2
    episodes = [e for e in ctx["latest"]["evidence"] if "action_timeline" in e]
    assert len(episodes) == 2
    assert ctx["history_selection"]["selected"] == 2
    assert ctx["search_selection"]["robot_api_call_upper_bound"] == 30
    assert ctx["allowed_axes"] == {AXIS: [0.0, 1.0]}
    assert body["model"] == "gpt-6-luna" and "max_output_tokens" not in body
    assert "Direct move" in body["instructions"] and "NOT an AFS/Random" in body["instructions"]
    plan = paired_plan(paths, ctx, proposal(body))
    assert plan["max_attempts"] == 3 and plan["robot_api_call_upper_bound"] == 30
    assert [c["scene"][AXIS] for c in plan["cases"]] == [0.5, 0.75, 0.25]
    assert [c["probe_purpose"] for c in plan["cases"]] == [
        "control_repeat",
        "relief_probe",
        "challenge_probe",
    ]
    for c in plan["cases"]:
        assert c["target_config"] == plan["cases"][0]["target_config"]
        assert {k for k in c["scene"] if c["scene"][k] != plan["reference_scene"][k]} <= {AXIS}
    assert not memory["brackets"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update(context_sha256="f" * 64),
        lambda p: p.update(anchor_case_id="wrong"),
        lambda p: p.update(axis="floor_friction"),
        lambda p: p["relief"].update(value=1.0),  # Already observed, not a new probe.
        lambda p: p["relief"].update(value=0.5),
        lambda p: p["relief"].update(value=0.3),
        lambda p: p["challenge"].update(value=0.7),
        lambda p: p["challenge"].update(value=-0.1),
        lambda p: p["challenge"].update(value=float("nan")),
        lambda p: p["challenge"].update(value=float("inf")),
        lambda p: p["challenge"].update(value=True),
        lambda p: p["challenge"].update(evidence_refs=["invented"]),
        lambda p: p.update(robot_action="push"),
    ],
)
def test_bad_proposals_never_create_scenes(tmp_path, mutation):
    paths = history(tmp_path)
    _, ctx, body = paired_request(paths)
    raw = proposal(body)
    mutation(raw)
    with pytest.raises(ValueError):
        paired_plan(paths, ctx, raw)
    assert not (tmp_path / "session").exists()


def test_both_observations_required_and_context_may_not_be_rewritten(tmp_path):
    paths = history(tmp_path)
    _, ctx, body = paired_request(paths)
    raw = proposal(body)
    for key in ("relief", "challenge"):
        raw[key]["evidence_refs"] = raw[key]["evidence_refs"][:1]
    with pytest.raises(ValueError, match="every supplied"):
        paired_plan(paths, ctx, raw)
    altered = copy.deepcopy(ctx)
    altered["task_contract"]["goal"]["radius_m"] = 5
    raw["context_sha256"] = digest(altered)
    with pytest.raises(ValueError, match="stale"):
        paired_plan(paths, altered, raw)


def test_incompatible_or_unreviewed_history_refused(tmp_path):
    paths = history(tmp_path)
    for bad in ([paths[0]], [paths[0], paths[0]], list(reversed(paths))):
        with pytest.raises(ValueError):
            paired_request(bad)
    failed = source(
        tmp_path / "failed", scene=GoalRegionFixture(box_lateral_fraction=0.25), outcome="FAIL"
    )
    with pytest.raises(ValueError, match="success controls"):
        paired_request([failed, paths[1]])
    different = source(
        tmp_path / "other", scene=GoalRegionFixture(box_lateral_fraction=0.7, floor_friction=0.6)
    )
    with pytest.raises(ValueError, match="differ only"):
        paired_request([different, paths[1]])


def test_one_call_prepares_three_scenes_and_reentry_never_resends(tmp_path):
    paths, session = prepare(tmp_path)
    before = [(p / "manifest.json").read_bytes() for p in paths]
    calls = []

    def caller(body, **kwargs):
        calls.append(body)
        return response(body)

    target = session.select(live=True, caller=caller)
    assert session.select(live=True, caller=caller) == target
    assert len(calls) == 1
    suite = BehaviorRegression(target, fingerprint=fingerprint)
    assert suite.state["attempts"] == []
    assert suite.summary()["max_attempts"] == 3
    assert suite.summary()["selection_costs"][0]["usage"]["input_tokens"] == 12
    assert (target / "preview/index.html").is_file()
    assert before == [(p / "manifest.json").read_bytes() for p in paths]


@pytest.mark.parametrize("kind", ["transport", "incomplete", "invalid"])
def test_error_costs_preserved_and_no_paid_retry(tmp_path, kind):
    _, session = prepare(tmp_path)
    calls = []

    def caller(body, **kwargs):
        calls.append(body)
        if kind == "transport":
            raise RuntimeError("network failed")
        out = response(body)
        if kind == "incomplete":
            out["status"] = "incomplete"
        else:
            out["output"][0]["content"][0]["text"] = "{}"
        return out

    for _ in range(2):
        with pytest.raises((ValueError, RuntimeError)):
            session.select(live=True, caller=caller)
    assert len(calls) == 1
    state, _ = session.store.load()
    assert state["calls_attempted"] == 1 and state["status"] == "NEEDS_ATTENTION"
    assert (session.root / "usage.json").is_file()
    assert (session.root / "error.json").is_file()
    assert not (session.root / "suite").exists()


def test_no_key_no_intent_and_saved_response_runs_offline(tmp_path, monkeypatch):
    _, session = prepare(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        session.select(live=True)
    assert session.store.load()[0]["calls_attempted"] == 0
    body = session.store.load()[0]["lock"]["request"]
    saved = tmp_path / "external_response.json"
    atomic_json(saved, response(body))
    target = session.select(response_path=saved)
    assert session.store.load()[0]["calls_attempted"] == 0
    assert json.loads((session.root / "usage.json").read_text())["new_calls_attempted"] == 0
    assert target.is_dir()


def test_drift_and_overlapping_output_refused_before_spending(tmp_path):
    paths, session = prepare(tmp_path)
    session.fingerprint = lambda c: {**fingerprint(c), "extra": "drift"}
    with pytest.raises(ValueError, match="changed"):
        session.select(live=True, caller=lambda *a, **k: pytest.fail("must not call API"))
    assert session.store.load()[0]["calls_attempted"] == 0
    with pytest.raises(ValueError, match="separate"):
        PairedSelection.prepare(
            paths[0] / "child", paths, fingerprint=fingerprint, execution_origin="mock"
        )


def test_saved_response_cannot_be_replaced_and_crash_intent_cannot_resend(tmp_path):
    _, session = prepare(tmp_path)
    state, revision = session.store.load()
    state.update(status="REQUEST_PENDING", calls_attempted=1)
    session.store.save(state, revision, "synthetic_crash")
    with pytest.raises(ValueError, match="no resend"):
        session.select(live=True, caller=lambda *a, **k: pytest.fail("must not call API"))
    atomic_json(session.root / "response.json", response(state["lock"]["request"]))
    target = session.select()  # Consume persisted response, no paid request.
    assert target.is_dir()


def test_synthetic_execution_reuses_runner_and_reports_observed_bracket(tmp_path):
    paths, session = prepare(tmp_path)
    target = session.select(live=True, caller=lambda body, **kw: response(body))
    calls = []

    def robot(cfg, directory, params):
        calls.append(params)
        directory.mkdir(parents=True)
        source(
            directory / "rollout",
            scene=cfg.scene(params),
            outcome="PASS" if params[AXIS] >= 0.5 else "FAIL",
        )
        return {"returncode": 0, "wall_s": 0.1, "interrupted": None}

    suite = BehaviorRegression(target, runner=robot, fingerprint=fingerprint)
    suite.run(live=True, max_new_attempts=1)
    assert len(calls) == 1 and suite.state["status"] == "READY"
    suite.run(live=True)
    assert len(calls) == 3 and suite.state["status"] == "COMPLETE"
    summary = suite.summary()
    assert [c["comparison"] for c in summary["cases"]] == [
        "OBSERVED_PASS",
        "OBSERVED_PASS",
        "OBSERVED_FAIL",
    ]
    report = suite.report()
    assert report.is_file() and (report.parent / "behavior/index.html").is_file()
    comparison = json.loads((report.parent / "paired_comparison.json").read_text())
    assert len(comparison["rows"]) == 5
    assert comparison["rows"][-1]["hypothesis"]["value"] == 0.25
    assert comparison["rows"][-1]["outcome"] == "FAIL"
    assert comparison["rows"][-1]["hypothesis_verdict"].startswith("NOT_ADJUDICATED")
    new_paths = paths + [suite._directory(a) / "rollout" for a in suite.state["attempts"]]
    memory, candidate, _, body = next_request(new_paths)
    assert body is None and memory["brackets"]
    assert candidate["parameters"][AXIS] == pytest.approx(0.375)
    # The old synthetic source helper deliberately contains a GIF placeholder;
    # reports/previews must not copy or generate it.
    assert not list(report.parent.rglob("*.gif"))
    assert not list((target / "preview").rglob("*.gif"))


def test_post_response_drift_records_usage_but_does_not_prepare_robot(tmp_path):
    _, session = prepare(tmp_path)

    def caller(body, **kwargs):
        session.fingerprint = lambda c: {**fingerprint(c), "extra": "drift"}
        return response(body)

    with pytest.raises(ValueError, match="changed"):
        session.select(live=True, caller=caller)
    assert json.loads((session.root / "usage.json").read_text())["usage"]["input_tokens"] == 12
    assert session.store.load()[0]["status"] == "NEEDS_ATTENTION"
    assert not (session.root / "suite").exists()


def test_concurrent_request_refused_before_api(tmp_path):
    _, session = prepare(tmp_path)
    with session.store.exclusive():
        with pytest.raises(RuntimeError, match="another process"):
            session.select(live=True, caller=lambda *a, **k: pytest.fail("no API"))
    assert session.store.load()[0]["calls_attempted"] == 0


def test_fully_covered_candidate_not_filtered_by_static_no_path(tmp_path):
    paths = history(tmp_path)
    _, ctx, body = paired_request(paths)
    raw = proposal(body)
    raw["challenge"]["value"] = 0.0
    plan = paired_plan(paths, ctx, raw)
    assert plan["cases"][2]["scene"][AXIS] == 0.0
    assert plan["cases"][2]["probe_purpose"] == "challenge_probe"


def test_cli_prepare_select_and_report_without_robot(tmp_path, monkeypatch, capsys):
    import runpy
    from pathlib import Path

    from failure_client.experiments import afs_paired_contrast, behavior_regression

    paths = history(tmp_path)
    original = PairedSelection.prepare
    monkeypatch.setattr(afs_paired_contrast, "regression_fingerprint", fingerprint)
    monkeypatch.setattr(behavior_regression, "regression_fingerprint", fingerprint)
    monkeypatch.setattr(
        PairedSelection,
        "prepare",
        lambda root, paths, **kw: original(root, paths, execution_origin="mock", **kw),
    )
    main = runpy.run_path(str(Path(__file__).resolve().parents[2] / "tools/run_afs_contrast.py"))[
        "main"
    ]
    root = tmp_path / "cli_session"
    assert (
        main(
            [
                "prepare-pair",
                "--run",
                str(paths[0]),
                "--run",
                str(paths[1]),
                "--output-dir",
                str(root),
            ]
        )
        == 0
    )
    assert '"robot_api_call_upper_bound": 30' in capsys.readouterr().out
    session = PairedSelection(root)
    body = session.store.load()[0]["lock"]["request"]
    saved = tmp_path / "response.json"
    atomic_json(saved, response(body))
    assert main(["select-pair", "--session", str(root), "--response", str(saved)]) == 0
    assert "REPORT=" in capsys.readouterr().out
    suite = BehaviorRegression(root / "suite")
    assert suite.state["attempts"] == []
    assert not list(root.rglob("rollout.mp4"))
