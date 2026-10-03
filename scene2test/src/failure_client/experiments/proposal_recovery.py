"""Explicit, offline fork for a first-proposal evidence-ID deletion typo.

Never edits the source campaign or its provider response. The fork is an
operator-assisted continuation, not an unmodified prospective benchmark.
"""

from __future__ import annotations

import copy
import fcntl
import json
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from failure_client.archive.regression_cases import build_failure_memory
from failure_client.evaluation.goal_run_reader import _hash_file, read_goal_run, read_json
from failure_client.evaluation.research_records import EpisodeRecord
from failure_client.methods.behavior_feedback import choose_probe, feedback_context
from failure_client.storage.research_store import ResearchStore
from llm_afs import behavior as b
from llm_afs import provider
from robot_vlm.debug_log import clean

from .local_goal_adapter import atomic_json
from .research_protocol import CampaignConfig, environment_fingerprint

SCHEMA = "evidence-ref-recovery-v1"
CLAIM = "operator_assisted_continuation_not_prospective_comparison"
# Deliberately not a generic code-drift override. Robot, selector, domain,
# measurement, dependency and resource changes are NOT allowed by this migration.
MIGRATION_FILES = frozenset(
    {
        "src/llm_afs/behavior.py",
        "src/llm_afs/behavior_request.py",
        "src/failure_client/experiments/research_campaign.py",
        "src/failure_client/experiments/proposal_recovery.py",
        "tools/run_afs_benchmark.py",
    }
)


def corrected_proposal(raw, ctx, replacements):
    """Operator must name the sole missing-character ID; no fuzzy auto-repair."""
    proposal = b.Proposal.model_validate(raw)
    allowed = b.evidence_ids(ctx)
    unknown = {r for s in proposal.spaces for r in s.evidence_refs} - set(allowed)
    if not isinstance(replacements, dict) or len(replacements) != 1:
        raise ValueError("exactly one explicit evidence ID replacement required")
    if set(replacements) != unknown:
        raise ValueError(
            "replacement must match the sole unknown reference; valid IDs are immutable"
        )
    old, new = next(iter(replacements.items()))
    if not isinstance(new, str) or not re.fullmatch(r"[0-9a-f]{63}", old):
        raise ValueError("recovery only supports a single deleted hex character")
    matches = [
        ref
        for ref in allowed
        if re.fullmatch(r"[0-9a-f]{64}", ref)
        and any(ref[:i] + ref[i + 1 :] == old for i in range(64))
    ]
    if matches != [new]:
        raise ValueError("replacement must be the unique allowed ID with one deleted character")
    fixed = copy.deepcopy(raw)
    for space in fixed["spaces"]:
        space["evidence_refs"] = [replacements.get(ref, ref) for ref in space["evidence_refs"]]
    # Includes stale-context, axis/range, duplicate-space and all reference checks.
    b.validate(b.Proposal.model_validate(fixed), ctx)
    return fixed


def _snapshot(root):
    # Even mode=ro can create WAL/SHM files. Query a private copy under the source
    # campaign lock, including a committed WAL if present; never touch source DB.
    with tempfile.TemporaryDirectory(prefix="afs-recovery-snapshot-") as temp:
        database = Path(temp) / "campaign.sqlite3"
        shutil.copyfile(root / database.name, database)
        wal = root / (database.name + "-wal")
        if wal.exists():
            shutil.copyfile(wal, Path(temp) / wal.name)
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            db.execute("BEGIN")
            row = db.execute(
                "SELECT revision,payload,sha256 FROM research_state WHERE id=1"
            ).fetchone()
            state = json.loads(row["payload"])
            ledger = [
                dict(r) for r in db.execute("SELECT * FROM research_ledger ORDER BY revision")
            ]
    protocol = read_json(root / "protocol.json")
    if (
        b.digest(state) != row["sha256"]
        or protocol != {"lock": state["lock"], "lock_sha256": state["lock_sha256"]}
        or b.digest(state["lock"]) != state["lock_sha256"]
    ):
        raise ValueError("source checkpoint/protocol integrity mismatch")
    if (
        not ledger
        or ledger[-1]["revision"] != row["revision"]
        or (ledger[-1]["state_sha256"] != row["sha256"])
    ):
        raise ValueError("source ledger does not match checkpoint")
    return {"state": state, "revision": row["revision"], "ledger": ledger, "protocol": protocol}


def _environment_changes(old, new):
    if {k: v for k, v in old.items() if k != "source_hashes"} != {
        k: v for k, v in new.items() if k != "source_hashes"
    }:
        raise ValueError("dependency/runtime/robot resources changed; recovery refused")
    before, after = old.get("source_hashes", {}), new.get("source_hashes", {})
    changes = {
        k: {"before": before.get(k), "after": after.get(k)}
        for k in sorted(before.keys() | after.keys())
        if before.get(k) != after.get(k)
    }
    if set(changes) - MIGRATION_FILES:
        raise ValueError(
            "unrelated code drift; recovery refused: "
            + ", ".join(sorted(set(changes) - MIGRATION_FILES))
        )
    if any(v["after"] is None for v in changes.values()):
        raise ValueError("source deletion is not an allowed recovery migration")
    return changes


def _checked_plan(root, spec, fingerprint):
    if set(spec) != {"proposal_id", "replacements", "note"}:
        raise ValueError("recovery spec requires proposal_id, replacements, note only")
    if not isinstance(spec["note"], str) or not spec["note"].strip():
        raise ValueError("operator recovery note required")
    snapshot = _snapshot(root)
    state = snapshot["state"]
    pending = state["pending"]
    if state["status"] != "NEEDS_ATTENTION" or not pending or pending["kind"] != "proposal":
        raise ValueError("recovery requires a stopped pending proposal")
    if state["lock"].get("recovery_sha256") or len(state["proposals"]) != 1:
        raise ValueError("only the first proposal of an unrecovered campaign is supported")
    row = state["proposals"][0]
    if (
        row["id"] != spec["proposal_id"]
        or pending["id"] != row["id"]
        or (pending["arm"] != {"method": "afs", "seed": row["seed"]})
        or row["status"] != "PENDING"
    ):
        raise ValueError("not the first unvalidated pending AFS proposal")
    if not re.fullmatch(r"proposal_\d{5}", row["id"]):
        raise ValueError("unsafe proposal identifier")
    cfg = CampaignConfig.model_validate(state["lock"]["config"])
    if cfg.model_dump() != state["lock"]["config"]:
        raise ValueError("recovery must not add defaults or change frozen config")
    environment = fingerprint(cfg)
    changes = _environment_changes(state["lock"]["environment"], environment)
    records = []
    for a in state["attempts"]:
        if a["status"] != "OBSERVED" or a["candidate"]["stage"] != "cold_start":
            raise ValueError("only completed cold-start attempts can be inherited")
        record = EpisodeRecord.model_validate(a["episode"])
        if record.status != "VALID" or read_goal_run(record.source) != record:
            raise ValueError("source evidence changed or is not VALID")
        if Path(record.source.path).resolve() != root / "attempts" / a["id"] / "rollout":
            raise ValueError("source attempt references an external archive")
        if record.source.method != a["method"] or record.source.seed != a["seed"]:
            raise ValueError("attempt attribution mismatch")
        records.append(record)
    if not records or any(r.condition_id != state["condition_id"] for r in records):
        raise ValueError("source condition mismatch")
    memory = build_failure_memory(
        [r for r in records if r.source.method == "afs" and r.source.seed == row["seed"]]
    )
    current = feedback_context(
        memory,
        history_limit=cfg.history_limit,
        remaining=cfg.valid_budget_per_seed - len(memory["episodes"]),
        scene_schema=cfg.scene_schema,
        selection_policy=cfg.selection_policy,
    )
    if b.digest(current) != b.digest(row["context"]):
        raise ValueError("saved proposal context differs from verified source evidence")
    directory = root / "proposals" / row["id"]
    request, response = (
        read_json(directory / "request.json"),
        read_json(directory / "response.json"),
    )
    payload = json.loads(request["input"][0]["content"])
    if request != row["request"] or b.digest(payload) != b.digest(
        {"context_sha256": b.digest(current), "context": current}
    ):
        raise ValueError("saved request/context mismatch")
    # Do not turn an API error, refusal, truncation or other validation defect into a repair.
    if response.get("error") is not None:
        raise ValueError("provider error is not recoverable as an evidence typo")
    raw = provider.extract_proposal(response)
    fixed = corrected_proposal(raw, current, spec["replacements"])
    candidate = choose_probe(fixed, current, memory)
    candidate["proposal_id"] = row["id"]
    for field, response_key in (
        ("usage", "usage"),
        ("returned_model", "model"),
        ("response_id", "id"),
    ):
        if row.get(field) != response.get(response_key):
            raise ValueError("recorded API usage/response identity mismatch")
    if not row.get("response_received"):
        raise ValueError("response must already be checkpointed before explicit repair")
    plan = {
        "schema_version": SCHEMA,
        "claim": CLAIM,
        "source_campaign": str(root),
        "source_snapshot_sha256": b.digest(snapshot),
        "source_lock_sha256": state["lock_sha256"],
        "source_revision": snapshot["revision"],
        "proposal_id": row["id"],
        "replacements": spec["replacements"],
        "note": clean(spec["note"]),
        "context_sha256": b.digest(current),
        "corrected_proposal_sha256": b.digest(fixed),
        "candidate_sha256": b.digest(candidate),
        "request_sha256": _hash_file(directory / "request.json"),
        "response_sha256": _hash_file(directory / "response.json"),
        "environment": environment,
        "source_changes": changes,
        "inherited_attempts": len(records),
        "inherited_afs_requests": len(state["proposals"]),
        "config": cfg.model_dump(),
        "api_called": False,
        "robot_launched": False,
        "archive_policy": "Inherited archives stay at source paths and are hash revalidated",
    }
    return plan, snapshot, candidate


def recover_campaign(
    root, spec, *, output=None, apply=False, expected_plan_sha256=None, fingerprint=None
):
    """Dry run by default. Applying requires the reviewed plan hash and a NEW directory."""
    root = Path(root).resolve()
    if apply and (output is None or not expected_plan_sha256):
        raise ValueError("apply requires a new output directory and expected plan SHA256")
    target = Path(output).resolve() if output is not None else None
    if target is not None and (
        target.exists() or target.is_relative_to(root) or root.is_relative_to(target)
    ):
        raise ValueError("recovery output must be new and disjoint from the source campaign")
    # A previous run creates this lock. Open read-only; never create/alter it on source.
    with (root / ".campaign.lock").open("rb") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("source campaign is active; recovery refused") from None
        plan, snapshot, candidate = _checked_plan(
            root, spec, fingerprint or environment_fingerprint
        )
        plan_hash = b.digest(plan)
        if not apply:
            return {"plan": plan, "plan_sha256": plan_hash, "applied": False}
        if expected_plan_sha256 != plan_hash:
            raise ValueError("recovery plan changed; review a fresh dry run")
        # All checks precede output creation; a interrupted copy is not a runnable campaign.
        directory = root / "proposals" / plan["proposal_id"]
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError("proposal symlinks are not supported")
        target.mkdir(parents=True, exist_ok=False)
        shutil.copytree(directory, target / "proposals" / plan["proposal_id"])
        audit = {**plan, "plan_sha256": plan_hash, "utc": datetime.now(UTC).isoformat()}
        atomic_json(target / "source_snapshot.json", snapshot)
        atomic_json(target / "recovery.json", audit)
        state = copy.deepcopy(snapshot["state"])
        state["lock"]["environment"] = plan["environment"]
        state["lock"]["recovery_sha256"] = b.digest(audit)
        state["lock_sha256"] = b.digest(state["lock"])
        row = state["proposals"][0]
        row.update(status="READY", candidate=candidate, evidence_ref_recovery=b.digest(audit))
        state.update(status="READY", reason="explicit_evidence_reference_recovery")
        atomic_json(
            target / "protocol.json", {"lock": state["lock"], "lock_sha256": state["lock_sha256"]}
        )
        verify_recovery(target, state)
        ResearchStore(target).save(
            state,
            -1,
            "explicit_recovery_fork",
            {
                "recovery_sha256": b.digest(audit),
                "source_campaign": str(root),
                "claim": CLAIM,
            },
        )
        return {
            "campaign": str(target),
            "plan_sha256": plan_hash,
            "applied": True,
            "claim": CLAIM,
            "inherited_attempts": plan["inherited_attempts"],
            "inherited_afs_requests": plan["inherited_afs_requests"],
            "api_called": False,
            "robot_launched": False,
        }


def verify_recovery(root, state):
    """Bind the derived candidate to unchanged request/response plus explicit mapping."""
    expected = state["lock"].get("recovery_sha256")
    marked = [p for p in state["proposals"] if p.get("evidence_ref_recovery")]
    if expected is None:
        if marked:
            raise ValueError("unbound proposal recovery marker")
        return None
    root = Path(root)
    audit = read_json(root / "recovery.json")
    if b.digest(audit) != expected or audit["schema_version"] != SCHEMA or audit["claim"] != CLAIM:
        raise ValueError("recovery audit integrity mismatch")
    if (
        len(marked) != 1
        or marked[0]["id"] != audit["proposal_id"]
        or (marked[0]["evidence_ref_recovery"] != expected)
    ):
        raise ValueError("recovery proposal binding mismatch")
    row = marked[0]
    snapshot = read_json(root / "source_snapshot.json")
    if b.digest(snapshot) != audit["source_snapshot_sha256"]:
        raise ValueError("recovery source snapshot mismatch")
    if state["lock"]["config"] != snapshot["state"]["lock"]["config"] or (
        state["lock"]["environment"] != audit["environment"]
    ):
        raise ValueError("recovery changed frozen budget/config/environment")
    directory = root / "proposals" / row["id"]
    for name in ("request", "response"):
        if _hash_file(directory / (name + ".json")) != audit[name + "_sha256"]:
            raise ValueError("recovery original " + name + " changed")
    if b.digest(row["context"]) != audit["context_sha256"]:
        raise ValueError("recovery context changed")
    raw = provider.extract_proposal(read_json(directory / "response.json"))
    fixed = corrected_proposal(raw, row["context"], audit["replacements"])
    if b.digest(fixed) != audit["corrected_proposal_sha256"] or (
        b.digest(row["candidate"]) != audit["candidate_sha256"]
    ):
        raise ValueError("recovered proposal/candidate changed")
    return audit
