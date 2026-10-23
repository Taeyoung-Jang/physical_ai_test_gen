"""Explicit offline fork of the first, unexecuted zero-width proposal only."""

import fcntl
import json
import shutil
from copy import deepcopy
from pathlib import Path

from failure_client.evaluation.goal_run_reader import _constant, _hash_file, _pairs, read_json
from failure_client.methods.autonomous_feedback import SearchBudget, selected_probe
from failure_client.storage.research_store import ResearchStore
from llm_afs import behavior as b
from llm_afs import provider

from .local_goal_adapter import atomic_json
from .proposal_recovery import _snapshot

MIGRATION_FILES = {
    "src/llm_afs/behavior.py",
    "src/llm_afs/behavior_request.py",
    "src/failure_client/methods/autonomous_feedback.py",
    "src/failure_client/methods/behavior_feedback.py",
    "src/failure_client/experiments/afs_autonomous.py",
    "src/failure_client/experiments/point_recovery.py",
    "tools/run_afs_autonomous.py",
}


def normalize_equal_ranges(raw):
    """Only replace equal low/high by the identical value; no clipping/rebinding."""
    b.Proposal.model_validate(raw)
    fixed = deepcopy(raw)
    count = 0
    for space in fixed["spaces"]:
        if space["low"] == space["high"]:
            space["value"] = space.pop("low")
            del space["high"]
            count += 1
    if not count:
        raise ValueError("recovery requires at least one equal-endpoint range")
    return fixed


def recover_point(source, output, *, apply=False, fingerprint_fn=None):
    """Dry-run by default. Never invokes a proposer or runner or mutates source."""
    from .afs_autonomous import MODE, AutonomousAFS, development_plan

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
        if (source / "attempts").exists() and any((source / "attempts").iterdir()):
            raise ValueError("rollout artifacts exist; recovery cannot assume no execution")
        if (
            old["schema_version"] != MODE
            or old["status"] != "NEEDS_ATTENTION"
            or old["attempts"]
            or old.get("selected") is not None
            or old["pending"] != {"kind": "proposal", "index": 0}
            or len(old["proposals"]) != 1
            or old["lock"].get("recovery_sha256")
        ):
            raise ValueError("recovery only supports first saved proposal before any rollout")
        row = old["proposals"][0]
        if row["id"] != "proposal_00000" or "candidate" in row:
            raise ValueError("proposal already selected or invalid id")
        directory = source / "proposals" / row["id"]
        if set(row["artifacts"]) != {"context.json", "request.json", "response.json"}:
            raise ValueError("complete hash-bound request/context/response required")
        for name, sha in row["artifacts"].items():
            if _hash_file(directory / name) != sha:
                raise ValueError("source proposal artifact mismatch")
        ctx, body, response = [
            read_json(directory / n) for n in ("context.json", "request.json", "response.json")
        ]
        if response.get("status") != "completed":
            raise ValueError("completed response required; no ambiguous request recovery")
        payload = body["input"]
        if len(payload) != 1 or json.loads(
            payload[0]["content"], object_pairs_hook=_pairs, parse_constant=_constant
        ) != {
            "context_sha256": b.digest(ctx),
            "context": ctx,
        }:
            raise ValueError("original request/context mismatch")
        original = provider.extract_proposal(response)
        fixed = normalize_equal_ranges(original)
        paths = [Path(r["source"]["path"]) for r in old["lock"]["plan"]["history"]]
        if any(
            output.is_relative_to(p.resolve()) or p.resolve().is_relative_to(output) for p in paths
        ):
            raise ValueError("recovery output overlaps historical evidence")
        budget = SearchBudget.model_validate(old["lock"]["plan"]["budget"])
        if (
            body.get("model") != budget.afs_model
            or row.get("usage") != response.get("usage")
            or row.get("returned_model") != response.get("model")
        ):
            raise ValueError("original request model or recorded usage differs from response")
        lock = development_plan(paths, budget, fingerprint_fn=fingerprint_fn)
        if lock["plan"] != old["lock"]["plan"]:
            raise ValueError("history, task, condition or budget differs from source")
        before, after = old["lock"]["environment"], lock["environment"]
        if {k: v for k, v in before.items() if k != "source_hashes"} != {
            k: v for k, v in after.items() if k != "source_hashes"
        }:
            raise ValueError("resources/runtime/environment drift cannot be recovered")
        changes = {
            k: {"before": before["source_hashes"].get(k), "after": after["source_hashes"].get(k)}
            for k in before["source_hashes"].keys() | after["source_hashes"].keys()
            if before["source_hashes"].get(k) != after["source_hashes"].get(k)
        }
        if not set(changes) <= MIGRATION_FILES:
            raise ValueError("unrelated source drift cannot be recovered")
        from failure_client.archive.regression_cases import build_failure_memory
        from failure_client.evaluation.research_records import EpisodeRecord
        from failure_client.methods.autonomous_feedback import selection

        memory = build_failure_memory(
            [EpisodeRecord.model_validate(r) for r in lock["plan"]["history"]]
        )
        candidate, current = selection(
            memory, [], budget, lock["plan"]["target_config"]["scene_schema"]
        )
        if candidate is not None or b.digest(ctx) != b.digest(current):
            raise ValueError("selection context changed; cannot rebind source response")
        chosen = selected_probe(fixed, current, memory)
        from .research_protocol import CampaignConfig

        CampaignConfig.model_validate(lock["plan"]["target_config"]).scene(chosen["parameters"])
        audit = {
            "schema_version": "equal-range-point-recovery-v1",
            "claim": "operator_assisted_development_continuation",
            "source": str(source),
            "source_revision": snapshot["revision"],
            "source_state_sha256": b.digest(old),
            "original_artifacts": row["artifacts"],
            "normalized_proposal_sha256": b.digest(fixed),
            "source_changes": changes,
            "budget_reset": False,
            "new_api_calls": 0,
            "robot_launched": False,
        }
        if not apply:
            return {"audit": audit, "candidate": chosen, "applied": False}
        output.mkdir(parents=True, exist_ok=False)
        target = output / "proposals" / row["id"]
        target.mkdir(parents=True)
        for name in row["artifacts"]:
            shutil.copyfile(directory / name, target / name)
        atomic_json(target / "normalized_proposal.json", fixed)
        atomic_json(output / "recovery.json", audit)
        lock["recovery_sha256"] = b.digest(audit)
        atomic_json(output / "protocol.json", {"lock": lock, "lock_sha256": b.digest(lock)})
        chosen["proposal_id"] = row["id"]
        copied = deepcopy(row)
        copied.update(candidate=chosen, recovery=True)
        copied["artifacts"]["normalized_proposal.json"] = _hash_file(
            target / "normalized_proposal.json"
        )
        state = {
            "schema_version": MODE,
            "lock": lock,
            "lock_sha256": b.digest(lock),
            "status": "READY",
            "reason": None,
            "pending": None,
            "selected": chosen,
            "attempts": [],
            "proposals": [copied],
        }
        ResearchStore(output).save(state, -1, "explicit_point_recovery", audit)
    engine = AutonomousAFS(output, fingerprint_fn=fingerprint_fn)
    return {"audit": audit, "applied": True, "session": str(output), "summary": engine.summary()}
