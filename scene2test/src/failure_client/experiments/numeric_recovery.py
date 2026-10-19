"""Offline, audited fork of a saved breadth response containing numeric outliers."""

import fcntl
import shutil
from copy import deepcopy
from pathlib import Path

from failure_client.archive.regression_cases import build_failure_memory
from failure_client.evaluation.behavior_measures import verify_episode_files
from failure_client.evaluation.goal_run_reader import _hash_file, read_json
from failure_client.evaluation.research_records import EpisodeRecord
from failure_client.methods.autonomous_feedback import selected_probe
from failure_client.storage.research_store import ResearchStore
from llm_afs import behavior as b
from llm_afs import provider
from llm_afs.behavior_request import NUMERIC_REJECTION_INSTRUCTIONS, request

from .local_goal_adapter import atomic_json
from .proposal_recovery import _snapshot

MIGRATION_FILES = {
    "src/llm_afs/behavior.py",
    "src/llm_afs/behavior_request.py",
    "src/failure_client/methods/autonomous_feedback.py",
    "src/failure_client/methods/behavior_feedback.py",
    "src/failure_client/experiments/numeric_recovery.py",
    "src/failure_client/experiments/afs_autonomous.py",
    "tools/run_afs_autonomous.py",
}


def recover_numeric(source, output, *, apply=False, fingerprint_fn=None):
    """Preserve all spent attempts/requests; never invoke proposer/runner or alter source."""
    from .afs_autonomous import (
        MODE,
        AutonomousAFS,
        development_plan,
        ensure_not_running,
        proposal_request_digest,
    )

    source, output = Path(source).resolve(), Path(output).resolve()
    if source.is_relative_to(output) or output.is_relative_to(source) or output.exists():
        raise ValueError("recovery output must be new and disjoint from source")
    with (source / ".campaign.lock").open("r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("source session is active") from None
        snapshot = _snapshot(source)
        old = snapshot["state"]
        if (
            old["schema_version"] != MODE
            or old["status"] != "NEEDS_ATTENTION"
            or old["reason"] != "execution_or_validation_error"
            or old.get("selected") is not None
            or not old["proposals"]
            or old["pending"] != {"kind": "proposal", "index": len(old["proposals"]) - 1}
            or old["lock"].get("recovery_sha256")
        ):
            raise ValueError("requires an unrecovered saved pending proposal validation stop")
        scratch = object.__new__(AutonomousAFS)
        scratch.root, scratch.state = source, deepcopy(old)
        budget = scratch.budget
        if budget.exploration_policy != "breadth-v1":
            raise ValueError("numeric recovery is restricted to breadth-v1")
        if (
            len(old["attempts"]) >= budget.max_attempts
            or (
                budget.valid_rollout_target is not None
                and sum(a.get("episode", {}).get("status") == "VALID" for a in old["attempts"])
                >= budget.valid_rollout_target
            )
            or len(old["proposals"]) > budget.max_afs_requests
        ):
            raise ValueError("cannot extend a completed or exhausted attempt budget")
        scratch._verify_evidence()
        for a in old["attempts"]:
            if a.get("episode", {}).get("status") != "VALID":
                raise ValueError(
                    "recovery requires completed valid prior attempts, no ambiguous rollout"
                )
            ensure_not_running(source / "attempts" / a["id"])
            verify_episode_files(EpisodeRecord.model_validate(a["episode"]))
        row = old["proposals"][-1]
        if (
            "candidate" in row
            or "rejection" in row
            or set(row["artifacts"]) != {"context.json", "request.json", "response.json"}
        ):
            raise ValueError("pending proposal must have only complete original request artifacts")
        directory = source / "proposals" / row["id"]
        ctx, body, response = [
            read_json(directory / n) for n in ("context.json", "request.json", "response.json")
        ]
        if (
            response.get("status") != "completed"
            or body.get("model") != budget.afs_model
            or row.get("usage") != response.get("usage")
            or row.get("returned_model") != response.get("model")
        ):
            raise ValueError("completed model/usage-bound response required")
        candidate, current = scratch._selection()
        if candidate is not None or b.digest(ctx) != b.digest(current):
            raise ValueError("original proposal context differs; no rebinding")
        current_body = request(
            ctx, budget.afs_model, selection_policy="autonomous_development_endpoint"
        )
        # Only the newly added numeric-rejection explanation may differ. Preserve
        # model, full input, schema, instructions before this suffix and all settings.
        legacy_body = deepcopy(current_body)
        legacy_body["instructions"] = legacy_body["instructions"].removesuffix(
            NUMERIC_REJECTION_INSTRUCTIONS
        )
        if proposal_request_digest(body) not in {
            proposal_request_digest(current_body),
            proposal_request_digest(legacy_body),
        }:
            raise ValueError(
                "source request differs beyond explicit numeric-rejection instruction suffix"
            )
        raw = provider.extract_proposal(response)
        memory = build_failure_memory(scratch._records())
        chosen = selected_probe(raw, ctx, memory)
        rejected = chosen["selection_audit"]["rejected"]
        numeric = [r for r in rejected if r["reason"] == "numeric_out_of_bounds"]
        if not numeric:
            raise ValueError(
                "numeric recovery requires an out-of-bounds candidate and valid alternative"
            )
        scratch.cfg.scene(chosen["parameters"])
        paths = [Path(r["source"]["path"]) for r in scratch.plan["history"]]
        if any(
            output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in paths
        ):
            raise ValueError("output overlaps historical evidence")
        lock = development_plan(paths, budget, fingerprint_fn=fingerprint_fn)
        if lock["plan"] != scratch.plan:
            raise ValueError("history/task/condition/budget drift cannot be recovered")
        before, after = old["lock"]["environment"], lock["environment"]
        if {k: v for k, v in before.items() if k != "source_hashes"} != {
            k: v for k, v in after.items() if k != "source_hashes"
        }:
            raise ValueError("resource/runtime/environment drift cannot be recovered")
        changes = {
            k: {"before": before["source_hashes"].get(k), "after": after["source_hashes"].get(k)}
            for k in sorted(before["source_hashes"].keys() | after["source_hashes"].keys())
            if before["source_hashes"].get(k) != after["source_hashes"].get(k)
        }
        if set(changes) - MIGRATION_FILES:
            raise ValueError("unrelated source drift cannot be recovered")
        audit = {
            "schema_version": "numeric-candidate-recovery-v1",
            "claim": "operator_assisted_development_continuation",
            "source": str(source),
            "source_revision": snapshot["revision"],
            "source_state_sha256": b.digest(old),
            "proposal_id": row["id"],
            "original_artifacts": row["artifacts"],
            "source_changes": changes,
            "rejected_candidates": numeric,
            "selected_space": chosen["space_index"],
            "budget_reset": False,
            "new_api_calls": 0,
            "robot_launched": False,
            "preserved_attempts": len(old["attempts"]),
            "preserved_afs_requests": len(old["proposals"]),
        }
        if not apply:
            return {"audit": audit, "candidate": chosen, "applied": False}
        output.mkdir(parents=True, exist_ok=False)
        # Keep original response bytes/indices and original past outcomes. Past
        # EpisodeRecord sources still point to their original verified archives.
        for name in ("proposals", "attempts"):
            if (source / name).exists():
                shutil.copytree(source / name, output / name)
        atomic_json(output / "source_state.json", old)
        atomic_json(output / "source_ledger.json", snapshot["ledger"])
        atomic_json(output / "source_protocol.json", snapshot["protocol"])
        audit["source_ledger_sha256"] = _hash_file(output / "source_ledger.json")
        audit["source_snapshot_artifacts"] = {
            name: _hash_file(output / name)
            for name in ("source_state.json", "source_ledger.json", "source_protocol.json")
        }
        atomic_json(output / "recovery.json", audit)
        lock["recovery_sha256"] = b.digest(audit)
        atomic_json(output / "protocol.json", {"lock": lock, "lock_sha256": b.digest(lock)})
        chosen["proposal_id"] = row["id"]
        state = deepcopy(old)
        state.update(
            lock=lock,
            lock_sha256=b.digest(lock),
            selected=chosen,
            pending=None,
            status="READY",
            reason=None,
        )
        state["proposals"][-1]["candidate"] = chosen
        ResearchStore(output).save(state, -1, "explicit_numeric_candidate_recovery", audit)
    engine = AutonomousAFS(output, fingerprint_fn=fingerprint_fn)
    return {"audit": audit, "applied": True, "session": str(output), "summary": engine.summary()}
