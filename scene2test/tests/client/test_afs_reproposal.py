"""Bounded NEW requests after completed candidate rejection, never transport retries."""

import json

import pytest

from failure_client.experiments.afs_autonomous import AutonomousAFS
from failure_client.methods.autonomous_feedback import SearchBudget

from .test_afs_contrast import fingerprint
from .test_branch_anchors import branch_point, engine
from .test_failure_directed import proposal


class Proposer:
    def __init__(self, mode="duplicate_then_valid"):
        self.contexts = []
        self.mode = mode

    def __call__(self, body, **kwargs):
        ctx = json.loads(body["input"][0]["content"])["context"]
        self.contexts.append(ctx)
        duplicate, _ = branch_point(ctx, axis="box_lateral_fraction")
        duplicate["value"] = 0.25  # Recreates the imported FAIL scene exactly.
        valid, _ = branch_point(ctx, axis="floor_friction")
        points = [duplicate]
        if self.mode == "alternatives":
            points.append(valid)
        elif self.mode == "duplicate_then_valid" and len(self.contexts) > 1:
            points = [valid]
        elif self.mode == "bounds":
            duplicate["value"] = 999.0
        elif self.mode == "timeout":
            raise TimeoutError("ambiguous transport failure")
        return {
            "status": "completed",
            "model": "synthetic-mock",
            "usage": {"input_tokens": 20, "output_tokens": 10},
            "output": [
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {"type": "output_text", "text": json.dumps(proposal(ctx, *points))}
                    ],
                }
            ],
        }


def setup(tmp_path, mode="duplicate_then_valid", cap=2):
    e = engine(tmp_path, reproposal_policy="bounded-rejection-v1", max_afs_requests=cap)
    e.proposer = Proposer(mode)
    return e


def test_new_proposal_receives_precise_rejection_and_consumes_same_budget(tmp_path):
    e = setup(tmp_path)
    result = e.run(live=True, max_new_attempts=1)
    assert result["afs_requests_attempted"] == 2
    assert result["afs_proposals_rejected"] == 1 and result["afs_requests_remaining"] == 0
    assert result["attempted"] == result["valid"] == len(e.runner.calls) == 1
    assert result["selection_costs"]["input_tokens"]["observed"] == 40
    ctx0, ctx1 = e.proposer.contexts
    assert ctx0["proposal_feedback"]["remaining_requests"] == 2
    assert ctx1["proposal_feedback"]["remaining_requests"] == 1
    rejection = ctx1["proposal_feedback"]["rejected_proposals"][0]
    endpoint = rejection["endpoints"][0]
    assert endpoint["reason"] == "already_observed" and endpoint["matching_case_ids"]
    assert endpoint["axis"] == "box_lateral_fraction" and endpoint["value"] == 0.25
    assert rejection["robot_launched"] is False
    assert "rejection.json" in e.state["proposals"][0]["artifacts"]
    assert "후보 거절" in e.report().read_text()
    assert ctx0["observed_single_axis_endpoints"]


def test_valid_alternative_runs_without_another_call(tmp_path):
    e = setup(tmp_path, "alternatives")
    result = e.run(live=True, max_new_attempts=1)
    assert result["afs_requests_attempted"] == result["attempted"] == 1
    assert result["afs_proposals_rejected"] == 0
    candidate = e.state["attempts"][0]["candidate"]
    assert candidate["axis"] == "floor_friction"
    assert candidate["selection_audit"]["rejected"][0]["reason"] == "already_observed"
    assert "already_observed" in e.report().read_text()


def test_all_rejections_stop_at_afs_cap_without_rollout_or_random(tmp_path):
    e = setup(tmp_path, "duplicates")
    result = e.run(live=True)
    assert result["status"] == "BUDGET_EXHAUSTED" and result["reason"] == "afs_request_budget"
    assert result["afs_requests_attempted"] == result["afs_proposals_rejected"] == 2
    assert result["attempted"] == result["fail"] == result["pass"] == 0
    assert not e.runner.calls and result["pending"] is None
    e.run(live=True)
    assert len(e.proposer.contexts) == 2


@pytest.mark.parametrize("mode, error", [("bounds", ValueError), ("timeout", TimeoutError)])
def test_schema_and_transport_errors_still_stop_without_reproposal(tmp_path, mode, error):
    e = setup(tmp_path, mode)
    with pytest.raises(error):
        e.run(live=True)
    assert len(e.proposer.contexts) == 1 and not e.runner.calls
    assert e.summary()["status"] == "NEEDS_ATTENTION"
    assert e.summary()["afs_proposals_rejected"] == 0


def test_old_stop_policy_does_not_start_extra_request(tmp_path):
    e = engine(tmp_path)
    e.proposer = Proposer("duplicates")
    with pytest.raises(ValueError, match="no novel"):
        e.run(live=True)
    assert len(e.proposer.contexts) == 1 and not e.runner.calls


def test_saved_duplicate_response_revalidated_without_resend(tmp_path, monkeypatch):
    e = setup(tmp_path)

    def crash(_):
        raise KeyboardInterrupt()

    monkeypatch.setattr(e, "_finish_proposal", crash)
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    assert len(e.proposer.contexts) == 1
    resumed = AutonomousAFS(
        e.root, runner=e.runner, proposer=e.proposer, fingerprint_fn=fingerprint
    )
    result = resumed.run(live=True, max_new_attempts=1)
    assert len(e.proposer.contexts) == 2 and len(e.runner.calls) == 1
    assert result["afs_proposals_rejected"] == 1


def test_interruption_after_committed_rejection_uses_next_request(tmp_path):
    e = setup(tmp_path)

    def interrupt(event):
        if event["event"] == "proposal_rejected":
            raise KeyboardInterrupt()

    e.on_event = interrupt
    with pytest.raises(KeyboardInterrupt):
        e.run(live=True)
    resumed = AutonomousAFS(
        e.root, runner=e.runner, proposer=e.proposer, fingerprint_fn=fingerprint
    )
    result = resumed.run(live=True, max_new_attempts=1)
    assert result["afs_requests_attempted"] == 2 and len(e.runner.calls) == 1


def test_rejection_artifact_tamper_blocks_resume(tmp_path):
    e = setup(tmp_path, "duplicates", cap=1)
    e.run(live=True)
    (e.root / "proposals/proposal_00000/rejection.json").write_text("{}")
    resumed = AutonomousAFS(
        e.root, runner=e.runner, proposer=e.proposer, fingerprint_fn=fingerprint
    )
    with pytest.raises(ValueError, match="changed"):
        resumed.run(live=True)
    assert len(e.proposer.contexts) == 1


def test_reproposal_policy_not_enabled_on_legacy_modes():
    with pytest.raises(ValueError, match="explicit failure-branch"):
        SearchBudget(reproposal_policy="bounded-rejection-v1")
