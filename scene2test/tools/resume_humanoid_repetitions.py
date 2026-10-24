"""Opt-in bounded rejection of malformed AFS action references; retain native evidence."""

import argparse
import json
from pathlib import Path

from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import PairedArm, PairedDiscovery
from llm_afs import provider
from llm_afs.behavior import digest

ROOT = Path(__file__).resolve().parents[1] / "development/humanoid_reasoning_fallback3_20261024_v1"
ERROR = "episode review cites unknown or duplicate action version"
POLICY = "bounded-action-reference-rejection-v1"


def reference_errors(response, ctx):
    """Report errors without interpreting concatenated digits or rewriting model output."""
    raw = provider.extract_proposal(response)
    evidence = {e["id"]: e for e in ctx["latest"]["evidence"]}
    errors = []
    for review in raw.get("episode_reviews", []):
        e = evidence.get(review["evidence_id"])
        if e is None:
            continue  # A different validation error must remain fatal.
        allowed = {a.get("observation_version") for a in e.get("action_timeline", [])}
        cited = review["observation_versions"]
        if len(set(cited)) != len(cited) or not set(cited) <= allowed:
            errors.append(
                {
                    "evidence_id": review["evidence_id"],
                    "cited": cited,
                    "allowed": sorted(allowed, key=str),
                }
            )
    return errors


class RecoveryArm(PairedArm):
    def _finish_proposal(self, row):
        try:
            return super()._finish_proposal(row)
        except ValueError as exc:
            if str(exc) != ERROR or self.budget.reproposal_policy != "bounded-rejection-v1":
                raise
            # super() already checked freshness, provider, saved context/request and schema.
            directory = self.root / "proposals" / row["id"]
            errors = reference_errors(
                read_json(directory / "response.json"), read_json(directory / "context.json")
            )
            if not errors or self.plan["method"] != "afs" or self.state["selected"] is not None:
                raise
            rejection = {
                "reason": "invalid_review_action_references",
                "policy": POLICY,
                "validation_error": ERROR,
                "action_reference_errors": errors,
                "instruction": "Use only listed allowed integer versions as separate array items; "
                "never concatenate digits. Original response is rejected, not repaired.",
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


class RecoveryCampaign(PairedDiscovery):
    def arm(self, seed, method):
        arm = super().arm(seed, method)  # Retain every native manifest/config check.
        arm.__class__ = RecoveryArm
        return arm


def progress(campaign):
    return [
        (a.state["status"], a.state["pending"], len(a.state["attempts"]), len(a.state["proposals"]))
        for a in campaign.arms()
    ]


def resume(campaign):
    # Collecting a rejected pending response changes state but launches zero episodes;
    # the host deliberately returns at that boundary. Continue only on durable progress.
    while True:
        before = progress(campaign)
        campaign.run(live=True, max_new_attempts=14, max_new_afs_requests=9)
        after = progress(campaign)
        if before == after or all(a.state["status"] == "COMPLETE" for a in campaign.arms()):
            return
        if any(
            a.state["status"] in {"NEEDS_ATTENTION", "BUDGET_EXHAUSTED", "TARGET_NOT_REACHED"}
            for a in campaign.arms()
        ):
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    # Same root batch lock as the original launcher: never run alongside that batch.
    import fcntl
    import runpy

    with (ROOT / ".run.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = runpy.run_path(str(Path(__file__).with_name("report_humanoid_repetitions.py")))[
            "report"
        ]
        snapshot = report(ROOT)  # Verifies all existing native evidence before mutation.
        if args.status or snapshot["all_complete"]:
            return 0
        bundle = read_json(ROOT / "repetitions.json")
        if digest(bundle["value"]) != bundle["sha256"]:
            raise ValueError("batch plan changed")
        print("RECOVERY_POLICY=" + POLICY, flush=True)
        remaining = {
            method: sum(7 - row["arms"][method]["valid"] for row in snapshot["repetitions"])
            for method in ("afs", "random")
        }
        print(
            "REMAINING_EPISODES=" + json.dumps(remaining) + "; existing budgets unchanged",
            flush=True,
        )
        if not args.live:
            print("Plan only; pass --live to reject confirmed invalid references and continue.")
            return 0
        policy_file = ROOT / "action_reference_recovery.json"
        policy = {
            "policy": POLICY,
            "tool_sha256": _hash_file(Path(__file__).resolve()),
            "batch_plan_sha256": bundle["sha256"],
            "existing_results_replayed": False,
            "budgets_changed": False,
            "scope": "Only completed AFS responses failing the exact action-version check; "
            "new requests consume original cap; HTTP/length/other errors stop.",
        }
        if policy_file.exists() and read_json(policy_file) != policy:
            raise ValueError("recovery policy changed")
        if not policy_file.exists():
            atomic_json(policy_file, policy)
        failed = False
        for row in bundle["value"]["repetitions"]:
            campaign = RecoveryCampaign(
                ROOT / row["directory"],
                on_event=lambda e: print(
                    "PAIRED_EVENT=" + json.dumps(e, ensure_ascii=False), flush=True
                ),
            )
            if all(a.state["status"] == "COMPLETE" for a in campaign.arms()):
                print(f"SKIP_COMPLETE seed={row['seed']}; no API/robot calls", flush=True)
                continue
            try:
                resume(campaign)
                print(f"REPORT={campaign.report()}", flush=True)
            except (ValueError, OSError, RuntimeError, KeyError) as exc:
                failed = True
                print(
                    f"STOPPED seed={row['seed']}: {type(exc).__name__}: {exc}; no automatic retry",
                    flush=True,
                )
            report(ROOT)
        final = report(ROOT)
        return 0 if final["all_complete"] and not failed else 2


if __name__ == "__main__":
    raise SystemExit(main())
