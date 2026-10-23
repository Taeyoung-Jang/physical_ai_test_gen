"""Offline point selection and explicit recovery; no real API/physics execution."""

import copy
import fcntl
import json

import pytest
from jsonschema import validate

from failure_client.evaluation.goal_run_reader import _hash_file
from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.experiments.point_recovery import normalize_equal_ranges, recover_point
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from llm_afs import behavior as b
from llm_afs import provider
from llm_afs.behavior_request import request

from .test_afs_autonomous import Proposer, setup
from .test_afs_contrast import fingerprint


def point(engine):
    _, ctx = engine._selection()
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    raw = provider.extract_proposal(Proposer()(body))
    space = raw["spaces"][0]
    space["value"] = space.pop("low")
    del space["high"]
    return ctx, body, raw


def test_point_schema_and_same_selector(tmp_path):
    engine, _, _ = setup(tmp_path, budget=SearchBudget(selection_policy="discovery-v1"))
    ctx, body, raw = point(engine)
    validate(raw, body["text"]["format"]["schema"])
    schema = body["text"]["format"]["schema"]
    assert schema["type"] == "object" and "anyOf" not in schema
    assert len(schema["properties"]["spaces"]["items"]["anyOf"]) == 2
    for definition in schema["$defs"].values():
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])
    result = selected_probe(raw, ctx, engine._memory())
    assert result["parameters"][raw["spaces"][0]["axis"]] == raw["spaces"][0]["value"]
    assert len(result["selection_audit"]["eligible"]) == 1
    assert "BEFORE a rollout" in body["instructions"]


@pytest.mark.parametrize(
    "bad", ["bounds", "nan", "extra_range", "reference", "context", "small", "duplicate"]
)
def test_point_never_bypasses_guards(tmp_path, bad):
    engine, _, _ = setup(tmp_path, budget=SearchBudget(selection_policy="discovery-v1"))
    ctx, _, raw = point(engine)
    s = raw["spaces"][0]
    axis = s["axis"]
    if bad == "bounds":
        s["value"] = ctx["allowed_axes"][axis][1] + 1
    elif bad == "nan":
        s["value"] = float("nan")
    elif bad == "extra_range":
        s.update(low=0.2, high=1.0)
    elif bad == "reference":
        s["evidence_refs"] = ["invented"]
    elif bad == "context":
        raw["context_sha256"] = "bad"
    elif bad == "small":
        lo, hi = ctx["allowed_axes"][axis]
        s["value"] = ctx["latest"]["parameters"][axis] + (hi - lo) * 0.01
    else:
        raw["spaces"].append(copy.deepcopy(s))
    with pytest.raises(ValueError):
        selected_probe(raw, ctx, engine._memory())


class EqualProposer(Proposer):
    def __call__(self, body, **kwargs):
        response = super().__call__(body, **kwargs)
        raw = provider.extract_proposal(response)
        raw["spaces"][0]["high"] = raw["spaces"][0]["low"]
        response["output"][0]["content"][0]["text"] = json.dumps(raw)
        return response


def failed(tmp_path):
    engine, robot, proposer = setup(tmp_path, proposer=EqualProposer())
    with pytest.raises(ValueError, match="require an in-bounds value or low < high"):
        engine.run(live=True)
    return engine, robot, proposer


def hashes(root):
    return {str(p.relative_to(root)): _hash_file(p) for p in root.rglob("*") if p.is_file()}


def test_recovery_preserves_source_cost_and_dispatches_once(tmp_path):
    engine, robot, proposer = failed(tmp_path)
    before = hashes(engine.root)
    output = tmp_path / "recovered"
    dry = recover_point(engine.root, output, fingerprint_fn=fingerprint)
    assert not dry["applied"] and not output.exists()
    assert hashes(engine.root) == before
    result = recover_point(engine.root, output, apply=True, fingerprint_fn=fingerprint)
    assert result["summary"]["afs_requests_attempted"] == 1
    assert result["summary"]["selection_costs"]["input_tokens"]["observed"] == 123
    assert hashes(engine.root) == before
    recovered = AutonomousAFS(output, runner=robot, proposer=proposer, fingerprint_fn=fingerprint)
    result = recovered.run(live=True, max_new_attempts=1)
    assert len(robot.calls) == len(proposer.calls) == 1
    assert result["attempted"] == 1
    assert result["budget"] == engine.summary()["budget"]
    assert recovered.report().is_file()
    recovered = AutonomousAFS(output, runner=robot, proposer=proposer, fingerprint_fn=fingerprint)
    recovered.run(live=True, max_new_attempts=0)
    assert len(robot.calls) == len(proposer.calls) == 1
    assert hashes(engine.root) == before


def test_recovery_refuses_unrelated_drift_and_active_source(tmp_path):
    engine, _, _ = failed(tmp_path)

    def drift(cfg):
        env = fingerprint(cfg)
        env["source_hashes"]["robot_policy"] = "changed"
        return env

    with pytest.raises(ValueError, match="unrelated source drift"):
        recover_point(engine.root, tmp_path / "drift", fingerprint_fn=drift)
    assert not (tmp_path / "drift").exists()
    with (engine.root / ".campaign.lock").open("r") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="active"):
            recover_point(engine.root, tmp_path / "active", fingerprint_fn=fingerprint)


def test_recovery_refuses_changed_normalized_value(tmp_path):
    engine, robot, proposer = failed(tmp_path)
    output = tmp_path / "recovered"
    recover_point(engine.root, output, apply=True, fingerprint_fn=fingerprint)
    target = output / "proposals/proposal_00000/normalized_proposal.json"
    from failure_client.experiments.local_goal_adapter import atomic_json

    raw = json.loads(target.read_text())
    raw["spaces"][0]["value"] += 0.1
    atomic_json(target, raw)
    recovered = AutonomousAFS(output, runner=robot, proposer=proposer, fingerprint_fn=fingerprint)
    with pytest.raises(ValueError, match="saved selection evidence changed"):
        recovered.run(live=True)
    assert not robot.calls and len(proposer.calls) == 1


def test_equal_range_requires_explicit_recovery(tmp_path):
    engine, _, _ = setup(tmp_path)
    ctx, _, raw = point(engine)
    s = raw["spaces"][0]
    s["low"] = s.pop("value")
    s["high"] = s["low"]
    with pytest.raises(ValueError, match="invalid scene proposal"):
        selected_probe(raw, ctx, engine._memory())
    fixed = normalize_equal_ranges(raw)
    assert selected_probe(fixed, ctx, engine._memory())["evidence"]["value"] == s["low"]
    assert "value" not in raw["spaces"][0]


def test_point_on_cooled_axis_is_rejected(tmp_path):
    engine, _, _ = setup(tmp_path)
    ctx, _, raw = point(engine)
    ctx["development_search"]["selectable_axes"].remove(raw["spaces"][0]["axis"])
    raw["context_sha256"] = b.digest(ctx)
    with pytest.raises(ValueError, match="cooled-down or exhausted"):
        selected_probe(raw, ctx, engine._memory())


def test_point_duplicate_scene_is_rejected(tmp_path):
    engine, _, _ = setup(tmp_path)
    ctx, _, raw = point(engine)
    raw["spaces"][0]["value"] = ctx["latest"]["parameters"][raw["spaces"][0]["axis"]]
    with pytest.raises(ValueError, match="no novel"):
        selected_probe(raw, ctx, engine._memory())


def test_recovery_cli_dry_run_needs_no_key(tmp_path, monkeypatch, capsys):
    import runpy

    engine, _, _ = failed(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    from failure_client.experiments import point_recovery

    monkeypatch.setattr(
        point_recovery,
        "recover_point",
        lambda source, output, apply=False: recover_point(
            source, output, apply=apply, fingerprint_fn=fingerprint
        ),
    )
    main = runpy.run_path("tools/run_afs_autonomous.py")["main"]
    target = tmp_path / "recovery"
    assert main(["recover-point", "--session", str(engine.root), "--output-dir", str(target)]) == 0
    assert not target.exists()
    assert "No API or robot executed" in capsys.readouterr().out
