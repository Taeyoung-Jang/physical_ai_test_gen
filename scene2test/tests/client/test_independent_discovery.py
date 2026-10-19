"""Independent evaluation lifecycle: CPU archives and fake providers only."""

import copy
import json

import pytest

from failure_client.experiments.discovery_evaluation import EvaluationDesign, evaluation_plan
from failure_client.experiments.independent_discovery import DiscoveryEvaluation
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.methods.behavior_feedback import uniform_scene

from .test_afs_breadth import point_for_slot
from .test_afs_contrast import Robot, fingerprint, source
from .test_cause_review import cause_engine, reviewed_raw
from .test_reference_roles_and_readiness import design


class Proposer:
    def __init__(self):
        self.contexts = []

    def __call__(self, body, **kwargs):
        ctx = json.loads(body["input"][0]["content"])["context"]
        self.contexts.append(ctx)
        assert ctx["development_search"]["external_history"] is False
        assert "externally seeded DEVELOPMENT" not in body["instructions"]
        assert body["text"]["format"]["strict"] is True
        intent = (
            "challenge" if "challenge" in ctx["failure_objective"]["allowed_intents"] else "relief"
        )
        p, anchor = point_for_slot(ctx, intent=intent)
        raw = reviewed_raw(ctx, p)
        raw["spaces"][0]["anchor_behavior_refs"] = anchor["evidence_ids"][:1]
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


class OutcomeRobot(Robot):
    def __init__(self, outcome="PASS", **kwargs):
        super().__init__(**kwargs)
        self.outcome = outcome

    def __call__(self, cfg, directory, params):
        directory.mkdir(parents=True)
        self.calls.append(params)
        source(directory / "rollout", scene=cfg.scene(params), outcome=self.outcome)
        receipt = {"returncode": 0, "wall_s": 0.1, "interrupted": None}
        atomic_json(directory / "receipt.json", receipt)
        return receipt


def setup(tmp_path, *, robot=None, seeds=None, cold=1, afs=5):
    control = cause_engine(tmp_path)
    data = design().model_dump()
    data.update(
        seeds=seeds or [17, 29],
        valid_per_seed=4,
        attempts_per_seed=5,
        afs_requests_per_seed=afs,
        cold_start_per_seed=cold,
    )
    data["search"].update(valid_rollout_target=4, max_attempts=5, max_afs_requests=afs)
    frozen = evaluation_plan(
        [r["source"]["path"] for r in control.plan["history"]],
        EvaluationDesign.model_validate(data),
        fingerprint_fn=fingerprint,
    )
    root = DiscoveryEvaluation.create(tmp_path / "evaluation", frozen, fingerprint_fn=fingerprint)
    proposer = Proposer()
    e = DiscoveryEvaluation(
        root, runner=robot or Robot(), proposer=proposer, fingerprint_fn=fingerprint
    )
    return e, proposer, control


def test_cold_start_is_seeded_charged_and_does_not_call_afs(tmp_path):
    e, p, control = setup(tmp_path)
    assert e.summary()["discovery_metrics"]["input_records"] == 0
    result = e.run(live=True, max_new_attempts=1)
    assert not p.contexts
    assert result["seeds"][0]["attempted"] == 1
    assert result["seeds"][0]["valid"] == 1
    assert result["seeds"][1]["attempted"] == 0
    s = e.seed(17)
    assert s.state["attempts"][0]["candidate"]["parameters"] == uniform_scene(
        17, "independent-cold-start-v1", 0, schema=s.cfg.scene_schema
    )
    assert {r.evidence_id for r in s._records()}.isdisjoint(
        {r["evidence_id"] for r in control.plan["history"]}
    )
    assert s._selection()[1]["development_search"]["external_history"] is False


def test_complete_seeds_are_isolated_and_repeat_run_spends_nothing(tmp_path):
    # Force valid PASS controls for proposal helpers, independently of sampled width.
    robot = OutcomeRobot()
    e, p, control = setup(tmp_path, robot=robot)
    result = e.run(live=True)
    assert result["status"] == "COMPLETE"
    assert len(robot.calls) == 8 and len(p.contexts) == 6
    first = {r.evidence_id for r in e.seed(17)._records()}
    second = {r.evidence_id for r in e.seed(29)._records()}
    external = {r["evidence_id"] for r in control.plan["history"]}
    for i, ctx in enumerate(p.contexts):
        refs = {
            x["id"]
            for x in ctx["latest"]["evidence"]
            if x["id"] not in {"case_memory", "observed_brackets"}
        }
        assert refs <= (first if i < 3 else second)
        assert not refs & external
    assert {g["seed"] for g in result["discovery_metrics"]["groups"]} == {17, 29}
    assert result["discovery_metrics"]["input_records"] == 8
    assert e.report().is_file()
    e.run(live=True)
    assert len(robot.calls) == 8


def test_all_fail_bootstrap_uses_failure_relief_then_stops_without_external_pass(tmp_path):
    robot = OutcomeRobot("FAIL")
    e, p, _ = setup(tmp_path, robot=robot, cold=2)
    result = e.run(live=True)
    assert len(robot.calls) == 3
    assert p.contexts[0]["failure_objective"]["allowed_intents"] == ["relief"]
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["joint_target_at_complete_budget"] is None
    assert result["seeds"][1]["attempted"] == 0


def test_saved_response_resume_does_not_resend_and_invocation_limit_is_global(tmp_path):
    robot = OutcomeRobot()
    e, p, _ = setup(tmp_path, robot=robot)
    e.run(live=True, max_new_attempts=1)

    def interrupt(event):
        if event["event"] == "proposal_response_collected":
            raise KeyboardInterrupt("saved complete response")

    e.kwargs["on_event"] = interrupt
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True, max_new_attempts=1)
    assert len(p.contexts) == 1
    e.kwargs["on_event"] = None
    e.run(live=True, max_new_attempts=1)
    assert len(p.contexts) == 1 and len(robot.calls) == 2
    result = e.run(live=True, max_new_attempts=3)
    assert len(robot.calls) == 5
    assert result["seeds"][0]["status"] == "COMPLETE"
    assert result["seeds"][1]["attempted"] == 1


def test_cold_start_exclusion_advances_to_next_predeclared_draw(tmp_path):
    robot = Robot(excluded=True)
    e, _, _ = setup(tmp_path, robot=robot, cold=2)
    e.run(live=True)
    first = dict(robot.calls[0])
    robot.excluded = False
    result = e.run(live=True, continue_after_exclusion=True, max_new_attempts=1)
    assert len(robot.calls) == 2 and robot.calls[1] != first
    assert result["seeds"][0]["attempted"] == 2
    assert result["seeds"][0]["excluded"] == 1
    assert result["seeds"][0]["valid"] == 1


def test_exclusion_stops_then_advances_without_retry_and_no_bootstrap_replacement(tmp_path):
    robot = Robot(excluded=True)
    e, p, _ = setup(tmp_path, robot=robot)
    result = e.run(live=True)
    assert result["status"] == "NEEDS_ATTENTION" and len(robot.calls) == 1
    e.run(live=True)
    assert len(robot.calls) == 1
    result = e.run(live=True, continue_after_exclusion=True)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["seeds"][0]["reason"] == "no_valid_cold_start_evidence"
    assert len(robot.calls) == 1 and not p.contexts


def test_completed_archive_collected_after_crash_without_resend(tmp_path):
    robot = Robot(crash=True)
    e, _, _ = setup(tmp_path, robot=robot, cold=2)
    with pytest.raises(RuntimeError, match="crash"):
        e.run(live=True, max_new_attempts=1)
    assert e.seed(17).state["pending"]["kind"] == "rollout"
    robot.crash = False
    # The ambiguous execution is collected, never dispatched again.
    result = e.run(live=True, max_new_attempts=1)
    assert len(robot.calls) == 2 and robot.calls[0] != robot.calls[1]
    assert result["seeds"][0]["valid"] == 2


def test_manifest_drift_output_reuse_and_explicit_live_guard(tmp_path):
    e, _, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="live"):
        e.run()
    with pytest.raises(FileExistsError):
        DiscoveryEvaluation.create(e.root, e.wrapped, fingerprint_fn=fingerprint)
    bad = copy.deepcopy(e.wrapped)
    bad["manifest"]["design"]["seeds"] = [99]
    with pytest.raises(ValueError, match="hash"):
        DiscoveryEvaluation.create(tmp_path / "bad", bad, fingerprint_fn=fingerprint)
    with pytest.raises(ValueError, match="re-freeze"):
        DiscoveryEvaluation.create(tmp_path / "drift", e.wrapped, fingerprint_fn=lambda _: {})
    assert not (tmp_path / "drift").exists()


def test_ambiguous_proposal_is_never_resent(tmp_path):
    e, _, _ = setup(tmp_path, robot=OutcomeRobot())
    e.run(live=True, max_new_attempts=1)
    calls = []

    def lost_response(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("remote response unknown")

    e.kwargs["proposer"] = lost_response
    with pytest.raises(RuntimeError, match="unknown"):
        e.run(live=True)
    with pytest.raises(RuntimeError, match="never resend"):
        e.run(live=True)
    assert len(calls) == 1 and e.seed(17).summary()["attempted"] == 1


def test_independent_policy_rejects_a_development_context(tmp_path):
    from llm_afs.behavior_request import request

    control = cause_engine(tmp_path)
    _, context = control._selection()
    with pytest.raises(ValueError, match="isolated seed"):
        request(context, "synthetic", selection_policy="independent_evaluation_endpoint")


def test_fdr_success_does_not_stop_before_full_predeclared_budget(tmp_path):
    class MixedRobot(OutcomeRobot):
        def __call__(self, cfg, directory, params):
            self.outcome = "FAIL" if self.calls else "PASS"
            return super().__call__(cfg, directory, params)

    robot = MixedRobot()
    e, _, _ = setup(tmp_path, robot=robot, seeds=[17])
    result = e.run(live=True)
    assert len(robot.calls) == 4 and result["status"] == "COMPLETE"
    assert result["seeds"][0]["fail"] == 3
    assert result["discovery_metrics"]["pooled_by_method"]["afs"]["failure_discovery_rate"] == 0.75


def test_request_budget_stops_without_unbudgeted_random_fallback(tmp_path):
    robot = OutcomeRobot()
    e, p, _ = setup(tmp_path, robot=robot, seeds=[17], afs=1)
    result = e.run(live=True)
    assert result["status"] == "BUDGET_EXHAUSTED"
    assert result["seeds"][0]["reason"] == "afs_request_budget"
    assert len(robot.calls) == 2 and len(p.contexts) == 1
    assert result["joint_target_at_complete_budget"] is None
