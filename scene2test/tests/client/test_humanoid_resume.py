"""Bounded malformed-reference recovery, synthetic evidence and zero paid calls."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from .test_afs_contrast import fingerprint
from .test_paired_discovery import Proposer, setup

MOD = runpy.run_path(str(Path(__file__).parents[2] / "tools/resume_humanoid_repetitions.py"))


class BadOnce(Proposer):
    def __init__(self, always=False, other=False):
        super().__init__()
        self.always, self.other = always, other

    def __call__(self, body, **kwargs):
        r = super().__call__(body, **kwargs)
        if len(self.calls) == 1 or self.always:
            content = r["output"][0]["content"][0]
            raw = json.loads(content["text"])
            review = raw["episode_reviews"][0]
            if self.other:
                review["observed_outcome"] = (
                    "PASS" if review["observed_outcome"] == "FAIL" else "FAIL"
                )
            else:
                review["observation_versions"] = [1516]
            content["text"] = json.dumps(raw)
        return r


def recover(e, proposer, runner):
    return MOD["RecoveryCampaign"](
        e.root, runner=runner, proposer=proposer, fingerprint_fn=fingerprint
    )


def signatures(root):
    return {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
        and (
            p.name in {"manifest.json", "protocol.json", "result.json", "decisions.jsonl"}
            or (p.parent.name.startswith("proposal_") and p.name.endswith(".json"))
        )
    }


def test_resume_pending_keeps_old_evidence_budget_and_no_completed_replay(tmp_path):
    e, _, runner, _ = setup(tmp_path)
    p = BadOnce()
    e.kwargs["proposer"] = p
    with pytest.raises(ValueError, match=MOD["ERROR"]):
        e.run(live=True, max_new_attempts=8, max_new_afs_requests=2)
    assert len(runner.calls) == 4 and len(p.calls) == 1
    old = signatures(e.root)
    recovered = recover(e, p, runner)
    MOD["resume"](recovered)
    result = recovered.summary()
    assert result["evaluation_complete"] and len(runner.calls) == 6 and len(p.calls) == 2
    arm = recovered.arm(17, "afs")
    assert len(arm.state["proposals"]) == arm.budget.max_afs_requests == 2
    assert arm.state["proposals"][0]["rejection"]["reason"] == "invalid_review_action_references"
    feedback = p.calls[1]["proposal_feedback"]["rejected_proposals"][0]
    assert feedback["action_reference_errors"][0]["cited"] == [1516]
    assert 1516 not in feedback["action_reference_errors"][0]["allowed"]
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha for path, sha in old.items()
    )
    MOD["resume"](recovered)
    assert len(runner.calls) == 6 and len(p.calls) == 2
    # Existing report generation accepts the new rejection without relabeling it a FAIL.
    assert recovered.report().is_file()


def test_repeated_bad_references_stop_at_original_request_cap(tmp_path):
    e, _, runner, _ = setup(tmp_path)
    p = BadOnce(always=True)
    recovered = recover(e, p, runner)
    MOD["resume"](recovered)
    assert len(p.calls) == 2 and len(runner.calls) == 4
    a = recovered.arm(17, "afs")
    assert a.state["status"] == "BUDGET_EXHAUSTED"
    assert len(a.state["attempts"]) == 2 and a.state["pending"] is None


def test_other_validation_error_remains_pending_no_retry(tmp_path):
    e, _, runner, _ = setup(tmp_path)
    p = BadOnce(other=True)
    recovered = recover(e, p, runner)
    with pytest.raises(ValueError, match="changed observed outcome"):
        MOD["resume"](recovered)
    a = recovered.arm(17, "afs")
    assert a.state["pending"]["kind"] == "proposal"
    assert len(p.calls) == 1 and len(runner.calls) == 4
    assert "rejection" not in a.state["proposals"][0]
