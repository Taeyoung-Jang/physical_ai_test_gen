"""Explicitly version a stopped paired run after removing only the byte guard.

No API or robot execution. Original files and ledgers remain untouched. Historical
episode paths remain bound to their original archives; copies are not new episodes.
"""

import argparse
import copy
import fcntl
import hashlib
import json
import shutil
import sqlite3
from contextlib import ExitStack
from pathlib import Path

from failure_client.experiments.local_goal_adapter import atomic_json
from failure_client.experiments.paired_discovery import (
    PairedDiscovery,
    checked_manifest,
    paired_fingerprint,
)
from failure_client.experiments.research_protocol import PROJECT, CampaignConfig
from failure_client.storage.research_store import ResearchStore
from llm_afs.behavior import digest

GUARD = (
    "    if len(content.encode()) > 250_000:\n"
    '        raise ValueError("context exceeds 250 KB; select fewer observations explicitly")\n'
)
ERROR = "context exceeds 250 KB; select fewer observations explicitly"


def read_state(root):
    with sqlite3.connect(f"{(root / 'campaign.sqlite3').as_uri()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT payload,sha256 FROM research_state WHERE id=1").fetchone()
    state = json.loads(row[0])
    if digest(state) != row[1]:
        raise ValueError("source state digest mismatch")
    return state


def migrate(source, output, *, prepare=False):
    source, output = source.resolve(), output.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("output must be a new disjoint folder")
    wrapped = json.loads((source / "manifest.json").read_text())
    manifest = checked_manifest(wrapped)
    cfg = CampaignConfig.model_validate(manifest["robot_config"])
    environment = paired_fingerprint(cfg)
    previous = manifest["environment"]
    key = "src/llm_afs/provider.py"
    old_text = (PROJECT / key).read_text()
    anchor = "    body = {\n"
    if GUARD in old_text or old_text.count(anchor) != 1:
        raise ValueError("expected the byte guard to be removed, with no other provider edits")
    restored = old_text.replace(anchor, GUARD + anchor)
    if hashlib.sha256(restored.encode()).hexdigest() != previous["source_hashes"][key]:
        raise ValueError("provider change is not exactly the byte guard removal")
    expected = copy.deepcopy(previous)
    expected["source_hashes"][key] = environment["source_hashes"][key]
    if environment != expected:
        raise ValueError("unrelated source/resources/runtime drift; cannot transition")
    roots = [source] + [
        source / "seeds" / str(seed) / method
        for seed in manifest["design"]["seeds"]
        for method in manifest["methods"]
    ]
    with ExitStack() as stack:
        for root in roots:
            stream = stack.enter_context((root / ".campaign.lock").open("r"))
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        states = [read_state(root) for root in roots]
        if states[0] != {"mode": manifest["schema_version"], "manifest_sha256": wrapped["sha256"]}:
            raise ValueError("parent binding changed")
        for root, state in zip(roots[1:], states[1:], strict=True):
            protocol = json.loads((root / "protocol.json").read_text())
            if protocol != {"lock": state["lock"], "lock_sha256": digest(state["lock"])}:
                raise ValueError("source protocol mismatch")
            if state["pending"] is not None or state["selected"] is not None:
                raise ValueError("pending work must never be resent by a transition")
            if any(a.get("episode", {}).get("status") != "VALID" for a in state["attempts"]):
                raise ValueError("transition requires finalized valid episodes only")
            if state["lock"]["environment"] != previous:
                raise ValueError("source arm environment differs")
            if state["status"] == "NEEDS_ATTENTION":
                errors = sorted((root / "errors").glob("*.json"))
                if not errors or json.loads(errors[-1].read_text()).get("message") != ERROR:
                    raise ValueError("only the local context-byte error may be acknowledged")
            elif state["status"] != "READY":
                raise ValueError("unexpected source status")
        counts = [
            {
                "arm": str(r.relative_to(source)),
                "attempts": len(s["attempts"]),
                "afs_requests": len(s["proposals"]),
            }
            for r, s in zip(roots[1:], states[1:], strict=True)
        ]
        audit = {
            "schema_version": "paired-byte-guard-removal-v1",
            "source": str(source),
            "source_manifest_sha256": wrapped["sha256"],
            "inherited_counts": counts,
            "source_state_sha256": [digest(s) for s in states],
            "change": "remove local context byte guard only",
            "api_calls_made": 0,
        }
        if not prepare:
            return audit
        shutil.copytree(
            source, output, ignore=shutil.ignore_patterns("campaign.sqlite3*", ".campaign.lock")
        )
        inventory = {}
        for path in source.rglob("*"):
            if (
                not path.is_file()
                or path.name.startswith("campaign.sqlite3")
                or path.name == ".campaign.lock"
            ):
                continue
            rel = path.relative_to(source)
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if hashlib.sha256((output / rel).read_bytes()).hexdigest() != sha:
                raise ValueError(f"copy mismatch: {rel}")
            inventory[str(rel)] = sha
        audit["copied_source_artifacts"] = inventory
        for root in roots:
            target = output / root.relative_to(source)
            with sqlite3.connect(
                f"{(root / 'campaign.sqlite3').as_uri()}?mode=ro", uri=True
            ) as old:
                with sqlite3.connect(target / "campaign.sqlite3") as new:
                    old.backup(new)
        new_manifest = copy.deepcopy(manifest)
        new_manifest["environment"] = environment
        new_wrapped = {"manifest": new_manifest, "sha256": digest(new_manifest)}
        checked_manifest(new_wrapped)
        atomic_json(output / "manifest.json", new_wrapped)
        for root, state in zip(roots, states, strict=True):
            target = output / root.relative_to(source)
            store = ResearchStore(target)
            copied, revision = store.load()
            if copied != state:
                raise ValueError("copied database state differs")
            if root == source:
                copied["manifest_sha256"] = new_wrapped["sha256"]
            else:
                copied["lock"]["environment"] = environment
                copied["lock"]["plan"]["manifest_sha256"] = new_wrapped["sha256"]
                copied["lock_sha256"] = digest(copied["lock"])
                copied.update(status="READY", reason=None)
                atomic_json(
                    target / "protocol.json",
                    {"lock": copied["lock"], "lock_sha256": copied["lock_sha256"]},
                )
                if (copied["attempts"], copied["proposals"]) != (
                    state["attempts"],
                    state["proposals"],
                ):
                    raise ValueError("historical budgets or evidence changed")
            store.save(
                copied,
                revision,
                "byte_guard_removal_transition",
                {"source": str(source), "source_state_sha256": digest(state)},
            )
        campaign = PairedDiscovery(output)
        for arm in campaign.arms():
            arm._fresh()
        for root, state in zip(roots, states, strict=True):
            if read_state(root) != state:
                raise ValueError("source state changed during transition")
        atomic_json(output / "transition.json", audit)
        return audit | {"output": str(output), "verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    result = migrate(args.source, args.output, prepare=args.prepare)
    result.pop("copied_source_artifacts", None)
    print(json.dumps(result, ensure_ascii=False))
