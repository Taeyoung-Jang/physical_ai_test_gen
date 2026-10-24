"""Required-review recovery uses native validation, bounded requests and saved evidence."""

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from .test_afs_contrast import fingerprint
from .test_humanoid_resume import BadOnce, signatures
from .test_paired_discovery import Proposer, setup

MOD = runpy.run_path(str(Path(__file__).parents[2] / "tools/finish_humanoid_repetitions.py"))


class MissingReview(Proposer):
    def __init__(self, always=False):
        super().__init__()
        self.always = always

    def __call__(self, body, **kwargs):
        response = super().__call__(body, **kwargs)
        if self.always or len(self.calls) == 1:
            content = response["output"][0]["content"][0]
            raw = json.loads(content["text"])
            ctx = json.loads(body["input"][0]["content"])["context"]
            required = ctx["failure_objective"]["cause_review_contract"]["required_evidence_ids"]
            other = next(e for e in ctx["latest"]["evidence"] if e["id"] != required[0])
            review = raw["episode_reviews"][0]
            review["evidence_id"] = other["id"]
            review["observed_outcome"] = other["outcome"]
            review["observation_versions"] = [
                a["observation_version"] for a in other.get("action_timeline", [])[:1]
            ]
            raw["episode_reviews"] = [review]
            content["text"] = json.dumps(raw)
        return response


def campaign(e, p, runner):
    return MOD["ReviewCampaign"](e.root, runner=runner, proposer=p, fingerprint_fn=fingerprint)


def test_pending_missing_review_resume_and_no_old_result_replay(tmp_path):
    e, _, runner, _ = setup(tmp_path)
    p = MissingReview()
    e.kwargs["proposer"] = p
    with pytest.raises(ValueError, match=MOD["MISSING"]):
        e.run(live=True, max_new_attempts=8, max_new_afs_requests=2)
    old = signatures(e.root)
    c = campaign(e, p, runner)
    MOD["BASE"]["resume"](c)
    assert c.summary()["evaluation_complete"]
    assert len(runner.calls) == 6 and len(p.calls) == 2
    row = c.arm(17, "afs").state["proposals"][0]
    assert row["rejection"]["reason"] == "missing_required_episode_review"
    assert row["rejection"]["missing_evidence_ids"]
    feedback = p.calls[1]["proposal_feedback"]["rejected_proposals"][0]
    assert feedback["required_evidence_ids"] == row["rejection"]["required_evidence_ids"]
    assert all(
        hashlib.sha256(Path(path).read_bytes()).hexdigest() == sha for path, sha in old.items()
    )
    assert c.report().is_file()
    MOD["BASE"]["resume"](c)
    assert len(runner.calls) == 6 and len(p.calls) == 2


def test_missing_review_does_not_increase_request_or_robot_budget(tmp_path):
    e, _, runner, _ = setup(tmp_path)
    p = MissingReview(always=True)
    c = campaign(e, p, runner)
    MOD["BASE"]["resume"](c)
    assert len(p.calls) == 2 and len(runner.calls) == 4
    a = c.arm(17, "afs")
    assert a.state["status"] == "BUDGET_EXHAUSTED"
    assert len(a.state["proposals"]) == a.budget.max_afs_requests


@pytest.mark.parametrize("other", [False, True])
def test_action_reference_support_and_other_error_stop(tmp_path, other):
    e, _, runner, _ = setup(tmp_path)
    p = BadOnce(other=other)
    c = campaign(e, p, runner)
    if other:
        with pytest.raises(ValueError, match="changed observed outcome"):
            MOD["BASE"]["resume"](c)
        assert len(p.calls) == 1 and c.arm(17, "afs").state["pending"]
    else:
        MOD["BASE"]["resume"](c)
        assert c.summary()["evaluation_complete"] and len(p.calls) == 2
