"""Versioned opt-in continuation for incomplete required reviews and action references."""

import argparse
import fcntl
import json
import runpy
from pathlib import Path

from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import PairedArm, PairedDiscovery
from llm_afs import provider
from llm_afs.behavior import digest

TOOLS = Path(__file__).resolve().parent
BASE = runpy.run_path(str(TOOLS / "resume_humanoid_repetitions.py"))
ROOT = BASE["ROOT"]
POLICY = "bounded-required-review-rejection-v2"
MISSING = "missing required episode review"


def review_errors(response, ctx, error):
    if error == BASE["ERROR"]:
        details = BASE["reference_errors"](response, ctx)
        return {"action_reference_errors": details} if details else None
    if error != MISSING:
        return None
    raw = provider.extract_proposal(response)
    required = ctx["failure_objective"]["cause_review_contract"]["required_evidence_ids"]
    cited = [r["evidence_id"] for r in raw["episode_reviews"]]
    missing = sorted(set(required) - set(cited))
    if not missing:
        return None
    return {
        "required_evidence_ids": required,
        "reviewed_evidence_ids": cited,
        "missing_evidence_ids": missing,
    }


class ReviewArm(PairedArm):
    def _finish_proposal(self, row):
        try:
            return super()._finish_proposal(row)
        except ValueError as exc:
            error = str(exc)
            if (
                error not in {MISSING, BASE["ERROR"]}
                or self.plan["method"] != "afs"
                or self.budget.reproposal_policy != "bounded-rejection-v1"
                or self.state["selected"] is not None
            ):
                raise
            # Native checks passed through saved context/request/provider/schema validation.
            directory = self.root / "proposals" / row["id"]
            details = review_errors(
                read_json(directory / "response.json"), read_json(directory / "context.json"), error
            )
            if not details:
                raise
            rejection = {
                "reason": (
                    "missing_required_episode_review"
                    if error == MISSING
                    else "invalid_review_action_references"
                ),
                "policy": POLICY,
                "validation_error": error,
                **details,
                "instruction": "Include one complete review for EVERY required_evidence_id, "
                "not just the latest episode. Keep observed outcomes unchanged. "
                "Action versions must be separate allowed integers. "
                "Do not fabricate reviews or concatenate action numbers.",
                "robot_launched": False,
                "budget_consumed": "one existing AFS request; no rollout slot or budget reset",
                "recovery_tool_sha256": _hash_file(Path(__file__).resolve()),
            }
            path = directory / "rejection.json"
            if path.exists() and read_json(path) != rejection:
                raise ValueError("existing rejection differs; never overwrite") from exc
            if not path.exists():
                atomic_json(path, rejection)
            row["artifacts"]["rejection.json"] = _hash_file(path)
            row["rejection"] = rejection
            self.state.update(selected=None, pending=None, status="READY", reason=None)
            self._save("proposal_rejected", {"id": row["id"], **rejection})


class ReviewCampaign(PairedDiscovery):
    def arm(self, seed, method):
        arm = super().arm(seed, method)
        arm.__class__ = ReviewArm
        return arm


def policy_record(root, bundle):
    previous = root / "action_reference_recovery.json"
    old = read_json(previous)
    if (
        old["tool_sha256"] != _hash_file(TOOLS / "resume_humanoid_repetitions.py")
        or old["batch_plan_sha256"] != bundle["sha256"]
    ):
        raise ValueError("previous recovery policy/source changed")
    return {
        "policy": POLICY,
        "tool_sha256": _hash_file(Path(__file__).resolve()),
        "previous_policy_sha256": _hash_file(previous),
        "batch_plan_sha256": bundle["sha256"],
        "budgets_changed": False,
        "existing_results_replayed": False,
        "scope": "Reject only completed responses failing required-review or action-reference "
        "checks; new requests consume original cap9; all other errors stop.",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true")
    p.add_argument("--status", action="store_true")
    args = p.parse_args()
    with (ROOT / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = runpy.run_path(str(TOOLS / "report_humanoid_repetitions.py"))["report"]
        snapshot = report(ROOT)
        if args.status or snapshot["all_complete"]:
            return 0
        bundle = read_json(ROOT / "repetitions.json")
        if bundle["sha256"] != digest(bundle["value"]):
            raise ValueError("batch plan changed")
        policy = policy_record(ROOT, bundle)
        remaining = {
            m: sum(7 - r["arms"][m]["valid"] for r in snapshot["repetitions"])
            for m in ("afs", "random")
        }
        print("REMAINING_EPISODES=" + json.dumps(remaining), flush=True)
        print("RECOVERY_POLICY=" + POLICY + "; original budgets unchanged", flush=True)
        if not args.live:
            print("Plan only; no API or robot calls. Pass --live to continue.")
            return 0
        path = ROOT / "required_review_recovery_v2.json"
        if path.exists() and read_json(path) != policy:
            raise ValueError("v2 recovery policy changed")
        if not path.exists():
            atomic_json(path, policy)
        failed = False
        for row in bundle["value"]["repetitions"]:
            campaign = ReviewCampaign(
                ROOT / row["directory"],
                on_event=lambda e: print(
                    "PAIRED_EVENT=" + json.dumps(e, ensure_ascii=False), flush=True
                ),
            )
            if all(a.state["status"] == "COMPLETE" for a in campaign.arms()):
                print(f"SKIP_COMPLETE seed={row['seed']}; no API/robot calls", flush=True)
                continue
            try:
                BASE["resume"](campaign)
                print(f"REPORT={campaign.report()}", flush=True)
            except (ValueError, OSError, RuntimeError, KeyError) as exc:
                failed = True
                print(f"STOPPED seed={row['seed']}: {exc}; no automatic retry", flush=True)
            report(ROOT)
        final = report(ROOT)
        return 0 if final["all_complete"] and not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
