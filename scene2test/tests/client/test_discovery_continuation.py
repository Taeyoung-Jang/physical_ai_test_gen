"""Policy/continuation tests using synthetic archives, never paid inference/physics."""

import copy
import gc
import hashlib
import json

import pytest
from jsonschema import ValidationError, validate

from failure_client.experiments.discovery_continuation import (
    CLAIM,
    DevelopmentContinuation,
    prepare_continuation,
)
from failure_client.experiments.independent_discovery import DiscoveryEvaluation
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.methods.autonomous_feedback import accounting, selected_probe
from failure_client.methods.behavior_feedback import NoEligibleEndpoint
from llm_afs.behavior_request import request

from .test_afs_contrast import fingerprint, source
from .test_behavior_memory import _rebind
from .test_cause_review import reviewed_raw
from .test_failure_directed import point
from .test_independent_discovery import OutcomeRobot, setup


class TimeoutRobot(OutcomeRobot):
    def __call__(self, cfg, directory, params):
        if len(self.calls) < 2:
            self.outcome = "FAIL"
            return super().__call__(cfg, directory, params)
        directory.mkdir(parents=True)
        self.calls.append(params)
        root = source(directory / "rollout", scene=cfg.scene(params), outcome="FAIL")
        result = json.loads((root / "result.json").read_text())
        result.update(
            reason="api_timeout", termination={"actor": "infrastructure", "reason": "api_timeout"}
        )
        result.update(
            task_outcome="INCONCLUSIVE",
            execution_valid=False,
            valid_execution=False,
            goal_reached=None,
            success=False,
        )
        atomic_json(root / "result.json", result)
        _rebind(root)
        receipt = {"returncode": 0, "wall_s": 300.1, "interrupted": None}
        atomic_json(directory / "receipt.json", receipt)
        return receipt


def excluded_campaign(tmp_path):
    e, _, _ = setup(tmp_path, robot=TimeoutRobot(), seeds=[17, 29], cold=2)
    result = e.run(live=True, max_new_attempts=3)
    assert result["status"] == "NEEDS_ATTENTION"
    assert e.seed(17).state["attempts"][-1]["episode"]["termination_reason"] == "api_timeout"
    # Close fixture initialization connections before byte-level immutability checks.
    gc.collect()
    return e


def v4_context(e):
    seed = e.seed(17)
    seed.state["lock"]["plan"]["budget"]["anchor_policy"] = "failure-diversity-v4"
    _, ctx = seed._selection()
    return seed, ctx


def transfer(ctx, *, intent="mechanism_transfer"):
    slot = ctx["exploration_allocation"]
    axis = slot["group_axes"][slot["required_group"]][0]
    anchor = next(a for a in ctx["anchor_catalog"] if intent in a["allowed_intents"])
    p = point(ctx, axis=axis, intent=intent)
    lo, hi = ctx["allowed_axes"][axis]
    base = anchor["parameters"][axis]
    value = max((lo, hi), key=lambda v: abs(v - base))
    if slot["required_form"] == "small":
        delta = 0.2 * (hi - lo)
        value = base + delta if base + delta <= hi else base - delta
    p.update(
        anchor_case_id=anchor["case_id"],
        anchor_rationale="Use observed anchor, not an excluded scene",
        value=value,
        behavior_refs=anchor["evidence_ids"][:1],
        evidence_refs=anchor["evidence_ids"][:1],
        extra_changes=[],
    )
    if slot["required_form"] == "combination":
        other = next(
            a for g, axes in slot["group_axes"].items() if g != slot["required_group"] for a in axes
        )
        low, high = ctx["allowed_axes"][other]
        p["extra_changes"] = [
            {
                "axis": other,
                "value": max((low, high), key=lambda v: abs(v - anchor["parameters"][other])),
            }
        ]
    raw = reviewed_raw(ctx, p)
    raw["spaces"][0]["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
    return raw


class TransferProposer:
    def __init__(self, reject=False):
        self.calls = []
        self.reject = reject

    def __call__(self, body, **kwargs):
        ctx = json.loads(body["input"][0]["content"])["context"]
        self.calls.append(ctx)
        raw = transfer(ctx)
        if self.reject:
            p = raw["spaces"][0]
            anchor = next(a for a in ctx["anchor_catalog"] if a["case_id"] == p["anchor_case_id"])
            p["value"] = anchor["parameters"][p["axis"]]
        validate(raw, body["text"]["format"]["schema"])
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": json.dumps(raw)}],
                }
            ],
        }


def hashes(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


def test_timeout_consumes_quota_but_not_behavior_cooldown_and_fail_transfer_works(tmp_path):
    original = excluded_campaign(tmp_path)
    with pytest.raises(ValueError, match="no eligible branch"):
        # Direct selector exposes the old policy deadlock; production wraps this stop.
        from failure_client.methods.autonomous_feedback import selection

        old = original.seed(17)
        selection(old._memory(), old.state["attempts"], old.budget, old.cfg.scene_schema)
    seed, ctx = v4_context(original)
    assert ctx["failure_objective"]["allowed_intents"] == ["mechanism_transfer", "relief"]
    assert ctx["failure_objective"]["behavior_cooldown_scope"] == "valid_episodes_only"
    audit = accounting(seed.state["attempts"], seed.cfg.design()["axes"], seed.budget)
    assert sum(audit["axis_attempts"].values()) == 2
    assert not audit["blocked_axes"]
    raw = transfer(ctx)
    body = request(ctx, "synthetic", selection_policy="autonomous_development_endpoint")
    validate(raw, body["text"]["format"]["schema"])
    assert selected_probe(raw, ctx, seed._memory())["branch_audit"]["anchor_outcome"] == "FAIL"
    assert "MUST use an unmixed observed PASS anchor" not in body["instructions"]
    raw["spaces"][0]["intent"] = "challenge"
    with pytest.raises(ValidationError):
        validate(raw, body["text"]["format"]["schema"])


def test_valid_relief_fail_does_not_deadlock_and_excluded_steps_do_not_age_it_out(tmp_path):
    e = excluded_campaign(tmp_path)
    seed, _ = v4_context(e)
    seed.state["attempts"][0]["candidate"]["evidence"]["intent"] = "relief"
    seed.state["attempts"] += [copy.deepcopy(seed.state["attempts"][-1]) for _ in range(4)]
    _, ctx = seed._selection()
    assert "relief" not in ctx["failure_objective"]["allowed_intents"]
    assert ctx["failure_objective"]["allowed_intents"] == ["mechanism_transfer"]


def test_dry_run_apply_preserve_source_counts_costs_and_fork_is_development(tmp_path):
    e = excluded_campaign(tmp_path)
    before = hashes(e.root)
    output = tmp_path / "continuation"
    dry = prepare_continuation(e.root, output, fingerprint_fn=fingerprint)
    assert not dry["applied"] and not output.exists()
    assert dry["remaining"]["17"] == {"attempts": 2, "afs_requests": 4, "valid_needed": 2}
    prepare_continuation(e.root, output, apply=True, fingerprint_fn=fingerprint)
    assert before == hashes(e.root)
    engine = DevelopmentContinuation(
        output, runner=OutcomeRobot("FAIL"), proposer=TransferProposer(), fingerprint_fn=fingerprint
    )
    prior = engine.summary()
    assert prior["claim"] == CLAIM and not prior["evaluation_complete"]
    assert prior["seeds"][0]["attempted"] == 3 and prior["seeds"][0]["afs_requests_attempted"] == 1
    assert prior["seeds"][0]["post_continuation_metrics"]["input_records"] == 0
    result = engine.run(
        live=True, max_new_attempts=1, max_new_afs_requests=1, continue_after_exclusion=True
    )
    assert result["seeds"][0]["attempted"] == 4 and result["seeds"][0]["valid"] == 3
    assert result["seeds"][0]["post_continuation_attempts"] == 1
    assert not result["evaluation_complete"] and result["joint_target_at_complete_budget"] is None
    assert before == hashes(e.root)
    assert engine.report().is_file()
    with pytest.raises(ValueError, match="manifest"):
        DiscoveryEvaluation(output, fingerprint_fn=fingerprint)


def test_one_request_limit_stops_rejections_without_spending_robot_attempt(tmp_path):
    e = excluded_campaign(tmp_path)
    output = tmp_path / "continuation"
    prepare_continuation(e.root, output, apply=True, fingerprint_fn=fingerprint)
    robot = OutcomeRobot()
    proposer = TransferProposer(reject=True)
    engine = DevelopmentContinuation(
        output, runner=robot, proposer=proposer, fingerprint_fn=fingerprint
    )
    result = engine.run(
        live=True, max_new_attempts=1, max_new_afs_requests=1, continue_after_exclusion=True
    )
    assert result["status"] == "READY" and result["seeds"][0]["reason"] == "invocation_afs_limit"
    assert len(proposer.calls) == 1 and not robot.calls
    assert (
        result["seeds"][0]["attempted"] == 3 and result["seeds"][0]["afs_requests_attempted"] == 2
    )


@pytest.mark.parametrize("drift", ["source", "resources"])
def test_unrelated_drift_refused(tmp_path, drift):
    e = excluded_campaign(tmp_path)
    env = copy.deepcopy(fingerprint(None))
    if drift == "source":
        env["source_hashes"]["src/robot_vlm/goal_runner.py"] = "x" * 64
    else:
        env["robot_resources"]["robot.xml"] = "x" * 64
    with pytest.raises(ValueError, match="drift"):
        prepare_continuation(e.root, tmp_path / "bad", fingerprint_fn=lambda _: env)
    assert not (tmp_path / "bad").exists()


def test_snapshot_tampering_blocks_resume(tmp_path):
    e = excluded_campaign(tmp_path)
    output = tmp_path / "continuation"
    prepare_continuation(e.root, output, apply=True, fingerprint_fn=fingerprint)
    (output / "source/seeds/17/state.json").write_text("{}")
    with pytest.raises(ValueError, match="snapshot"):
        DevelopmentContinuation(output, fingerprint_fn=fingerprint).summary()


def test_exact_excluded_scene_cannot_be_silently_replayed(tmp_path):
    e = excluded_campaign(tmp_path)
    seed, ctx = v4_context(e)
    candidate = selected_probe(transfer(ctx), ctx, seed._memory())
    ctx["excluded_scene_parameters"].append(candidate["parameters"])
    with pytest.raises(NoEligibleEndpoint) as caught:
        selected_probe(transfer(ctx), ctx, seed._memory())
    assert caught.value.rejections[0]["reason"] == "excluded_scene_requires_explicit_replay"


def test_ambiguous_source_and_changed_prefix_are_rejected(tmp_path):
    e = excluded_campaign(tmp_path)
    output = tmp_path / "continuation"
    prepare_continuation(e.root, output, apply=True, fingerprint_fn=fingerprint)
    s = DevelopmentContinuation(output, fingerprint_fn=fingerprint).seed(17)
    s.state["attempts"][0]["candidate"]["evidence"]["source"] = "changed"
    s._save("synthetic_tamper")
    with pytest.raises(ValueError, match="preserved"):
        DevelopmentContinuation(output, fingerprint_fn=fingerprint).summary()
    original = e.seed(17)
    original.state["pending"] = {"kind": "proposal", "index": 0}
    original._save("synthetic_ambiguous")
    with pytest.raises(ValueError, match="completed-observation"):
        prepare_continuation(e.root, tmp_path / "bad", fingerprint_fn=fingerprint)


def test_complete_saved_new_response_is_collected_without_resend(tmp_path):
    e = excluded_campaign(tmp_path)
    output = tmp_path / "continuation"
    prepare_continuation(e.root, output, apply=True, fingerprint_fn=fingerprint)
    proposer = TransferProposer()
    robot = OutcomeRobot("FAIL")

    def interrupt(event):
        if event["event"] == "proposal_response_collected":
            raise KeyboardInterrupt("saved response")

    engine = DevelopmentContinuation(
        output, runner=robot, proposer=proposer, fingerprint_fn=fingerprint, on_event=interrupt
    )
    with pytest.raises(KeyboardInterrupt):
        engine.run(
            live=True, max_new_attempts=1, max_new_afs_requests=1, continue_after_exclusion=True
        )
    assert len(proposer.calls) == 1 and not robot.calls
    engine.kwargs["on_event"] = None
    engine.kwargs["proposer"] = lambda *a, **k: pytest.fail("must not resend")
    result = engine.run(live=True, max_new_attempts=1, max_new_afs_requests=1)
    assert len(robot.calls) == 1 and result["seeds"][0]["attempted"] == 4
