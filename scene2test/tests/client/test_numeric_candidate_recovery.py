"""Numeric candidate rejection and audited saved-response continuation, CPU only."""

import copy
import hashlib
import json

import pytest

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.experiments.numeric_recovery import recover_numeric
from failure_client.methods.autonomous_feedback import selected_probe
from failure_client.methods.behavior_feedback import NoEligibleEndpoint
from llm_afs import behavior as b

from .test_afs_breadth import SlotProposer, broad_engine, point_for_slot
from .test_afs_contrast import fingerprint
from .test_failure_directed import proposal


@pytest.mark.parametrize("position", [0, 1])
@pytest.mark.parametrize("secondary", [False, True])
def test_numeric_outlier_does_not_discard_valid_alternative(tmp_path, position, secondary):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    if secondary:
        ctx["exploration_allocation"]["required_form"] = "combination"
    good, _ = point_for_slot(ctx)
    bad = copy.deepcopy(good)
    target = bad["extra_changes"][0] if secondary else bad
    target["value"] = ctx["allowed_axes"][target["axis"]][1] + 0.2
    points = [good]
    points.insert(position, bad)
    raw = proposal(ctx, *points)
    before = copy.deepcopy(raw)
    c = selected_probe(raw, ctx, e._memory())
    assert raw == before and c["space_index"] == 1 - position
    assert c["evidence"] == good
    rejected = c["selection_audit"]["rejected"]
    assert rejected[0]["reason"] == "numeric_out_of_bounds"
    assert rejected[0]["violations"][0]["value"] == target["value"]


@pytest.mark.parametrize(
    "bad", ["reference", "schema", "nonfinite", "unknown_axis", "cooldown", "stale"]
)
def test_other_errors_on_outlier_still_stop_whole_response(tmp_path, bad):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    good, _ = point_for_slot(ctx)
    outlier = copy.deepcopy(good)
    outlier["value"] = 10.0
    if bad == "reference":
        outlier["evidence_refs"] = ["invented"]
    elif bad == "schema":
        outlier["unexpected"] = True
    elif bad == "nonfinite":
        outlier["value"] = float("nan")
    elif bad == "unknown_axis":
        outlier["axis"] = "robot_torque"
    elif bad == "cooldown":
        ctx["development_search"]["selectable_axes"].remove(outlier["axis"])
    raw = proposal(ctx, good, outlier)
    if bad == "stale":
        raw["context_sha256"] = "wrong"
    with pytest.raises(ValueError):
        selected_probe(raw, ctx, e._memory())


def test_all_outliers_are_recorded_rejections_not_failure_or_random(tmp_path):
    e = broad_engine(tmp_path)
    _, ctx = e._selection()
    p, _ = point_for_slot(ctx)
    p["value"] = 100.0
    with pytest.raises(NoEligibleEndpoint) as exc:
        selected_probe(proposal(ctx, p), ctx, e._memory())
    assert exc.value.rejections[0]["reason"] == "numeric_out_of_bounds"
    assert not e.runner.calls


class MixedThird(SlotProposer):
    def __call__(self, body, **kw):
        response = super().__call__(body, **kw)
        if len(self.calls) == 3:
            raw = json.loads(response["output"][0]["content"][0]["text"])
            bad = copy.deepcopy(raw["spaces"][0])
            bad["extra_changes"][0]["value"] = 100.0
            raw["spaces"].append(bad)
            response["output"][0]["content"][0]["text"] = json.dumps(raw)
        return response


def stopped(tmp_path, monkeypatch):
    import failure_client.experiments.afs_autonomous as module

    e = broad_engine(tmp_path, max_attempts=4, valid_rollout_target=4)
    e.proposer = MixedThird()
    original = module.selected_probe

    def legacy(raw, ctx, memory):
        b.validate(b.endpoint_proposal(raw, ctx), ctx)  # Original whole-response stop.
        return original(raw, ctx, memory)

    with monkeypatch.context() as m:
        m.setattr(module, "selected_probe", legacy)
        with pytest.raises(ValueError, match="outside frozen scene domain"):
            e.run(live=True, max_new_attempts=3)
    assert len(e.runner.calls) == 2 and len(e.proposer.calls) == 3
    return e


def files(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_recovery_preserves_original_attempts_costs_and_no_resend(tmp_path, monkeypatch):
    e = stopped(tmp_path, monkeypatch)
    before = files(e.root)
    out = tmp_path / "recovered"
    dry = recover_numeric(e.root, out, fingerprint_fn=fingerprint)
    assert not out.exists() and not dry["applied"] and files(e.root) == before
    result = recover_numeric(e.root, out, apply=True, fingerprint_fn=fingerprint)
    assert files(e.root) == before
    assert result["summary"]["attempted"] == 2 and result["summary"]["afs_requests_attempted"] == 3
    assert result["summary"]["new_execution_costs"] == e.summary()["new_execution_costs"]
    assert result["summary"]["selection_costs"] == e.summary()["selection_costs"]

    def no_proposer(*a, **kw):
        raise AssertionError("saved response must not be resent")

    resumed = AutonomousAFS(out, runner=e.runner, proposer=no_proposer, fingerprint_fn=fingerprint)
    for a in e.state["attempts"]:
        assert a in resumed.state["attempts"]
    r = resumed.run(live=True, max_new_attempts=1)
    assert r["attempted"] == 3 and r["afs_requests_attempted"] == 3 and len(e.runner.calls) == 3
    assert len(resumed.state["attempts"][2]["candidate"]["changed_axes"]) == 2
    assert files(e.root) == before


@pytest.mark.parametrize("kind", ["unrelated", "resources"])
def test_recovery_refuses_other_drift(tmp_path, monkeypatch, kind):
    e = stopped(tmp_path, monkeypatch)

    def drift(cfg):
        env = copy.deepcopy(fingerprint(cfg))
        env["source_hashes" if kind == "unrelated" else "robot_resources"]["runner"] = "different"
        return env

    with pytest.raises(ValueError, match="drift|changed; new control required"):
        recover_numeric(e.root, tmp_path / "bad", fingerprint_fn=drift)
    assert not (tmp_path / "bad").exists()


def test_all_numeric_rejections_consume_afs_cap_without_robot_attempt(tmp_path):
    e = broad_engine(tmp_path, max_afs_requests=2)
    calls = []

    def proposer(body, **kw):
        ctx = json.loads(body["input"][0]["content"])["context"]
        calls.append(ctx)
        p, _ = point_for_slot(ctx)
        p["value"] = 100.0
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 2, "output_tokens": 1},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(proposal(ctx, p))}],
                }
            ],
        }

    e.proposer = proposer
    result = e.run(live=True)
    assert result["reason"] == "afs_request_budget"
    assert result["afs_requests_attempted"] == result["afs_proposals_rejected"] == 2
    assert result["attempted"] == result["fail"] == 0 and not e.runner.calls
    assert (
        calls[1]["proposal_feedback"]["rejected_proposals"][0]["endpoints"][0]["reason"]
        == "numeric_out_of_bounds"
    )


@pytest.mark.parametrize("what", ["original_response", "recovery_snapshot"])
def test_recovery_tamper_is_rejected(tmp_path, monkeypatch, what):
    e = stopped(tmp_path, monkeypatch)
    out = tmp_path / "recovered"
    if what == "original_response":
        (e.root / "proposals/proposal_00002/response.json").write_text("{}")
        with pytest.raises(ValueError, match="changed"):
            recover_numeric(e.root, out, fingerprint_fn=fingerprint)
        assert not out.exists()
    else:
        recover_numeric(e.root, out, apply=True, fingerprint_fn=fingerprint)
        (out / "source_ledger.json").write_text("[]")
        with pytest.raises(ValueError, match="snapshot changed"):
            AutonomousAFS(out, runner=e.runner, proposer=e.proposer, fingerprint_fn=fingerprint)
