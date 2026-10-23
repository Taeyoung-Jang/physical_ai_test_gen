"""Prepare a versioned provider transition; preserve completed bootstrap and old intent."""

import argparse
import json
import shutil
from copy import deepcopy
from pathlib import Path

import run_robot_arm_search as cli

from robot_arm import placement, search

BASE = cli.PROJECT / "experiments/robot_arm_libero"


def inspect(source, source_audit, confirmed_pre_send_failure):
    if not confirmed_pre_send_failure:
        raise ValueError("Transition requires the user-reported pre-send missing-key traceback")
    m = search.read(source / "manifest.json")
    digest = search.sha(source / "manifest.json")
    if digest != (source / "manifest.sha256").read_text().strip():
        raise ValueError("old manifest changed")
    audit = search.read(source_audit)
    if (
        audit["manifest_sha256"] != digest
        or audit["changed_sources"]
        or audit["source"] != str(source.resolve())
        or audit["verified_source_hashes"] != m["source_hashes"]
    ):
        raise ValueError("pre-edit source audit mismatch")
    allowed = {
        str(cli.PROJECT / "src/robot_arm/search.py"),
        str(cli.PROJECT / "tools/run_robot_arm_search.py"),
    }
    for path, h in m["source_hashes"].items():
        if path not in allowed and search.sha(path) != h:
            raise ValueError("robot/upstream/placement source changed: " + path)
    c = search.validate(m["config"])
    if c.get("afs_api_provider", "openai") != "openai":
        raise ValueError("source must be the pre-adaptive OpenAI campaign")
    expected = {
        source / f"seed_{s}" / method / f"attempt_{i:05d}"
        for s in c["seeds"]
        for method in c["methods"]
        for i in range(c["bootstrap"])
    }
    results = {p.parent for p in source.glob("seed_*/*/attempt_*/result.json")}
    if results != expected:
        raise ValueError("exactly all bootstrap outcomes required; no adaptive outcomes allowed")
    for directory in expected:
        candidate = search.read(directory / "candidate.json")
        seed = int(directory.parents[1].name.split("_")[1])
        index = int(directory.name.split("_")[-1])
        if candidate["positions"] != search.uniform(c, seed, index) or candidate[
            "scene_seed"
        ] != search.scene_seed(seed, index):
            raise ValueError("bootstrap candidate/seed mismatch")
        if search.read(directory / "robot_intent.json") != candidate:
            raise ValueError("bootstrap intent mismatch")
        result = search.read(directory / "result.json")
        if result != search.read(directory / "receipt.json") or result["status"] != "VALID":
            raise ValueError("bootstrap must have matching valid receipt/result")
        initial = search.read(directory / "initial_state.json")
        if not initial["valid"] or initial["requested"] != candidate["positions"]:
            raise ValueError("bootstrap initial geometry invalid")
        trace = [json.loads(x) for x in (directory / "trace.jsonl").read_text().splitlines()]
        if len(trace) != result["steps"][0] or any(x["success"] for x in trace) != (
            result["task_outcome"] == "PASS"
        ):
            raise ValueError("bootstrap trace/outcome mismatch")
    pending = source / f"seed_{c['seeds'][0]}" / "afs" / f"attempt_{c['bootstrap']:05d}"
    if list(source.glob("seed_*/*/attempt_*/response.json")):
        raise ValueError("saved API response prevents this bootstrap-only transition")
    requests = list(source.glob("seed_*/*/attempt_*/request.json"))
    if requests != [pending / "request.json"]:
        raise ValueError("unexpected historical API intents")
    if any(
        (pending / n).exists()
        for n in ("robot_intent.json", "candidate.json", "worker_started.json")
    ):
        raise ValueError("pending slot already has robot/candidate state")
    if search.read(pending / "request.json") != search.proposal_body(
        c, search.history_for(source, c["seeds"][0], "afs")
    ):
        raise ValueError("historical request/history mismatch")
    # Read and verify all files before copy; do not follow symlinks or open any DB.
    hashes = {}
    for directory in sorted(expected):
        for path in directory.rglob("*"):
            if path.is_symlink():
                raise ValueError("symlink in bootstrap archive")
            if path.is_file():
                hashes[str(path.relative_to(source))] = search.sha(path)
    return m, audit, expected, hashes, pending


def prepare(source, output, source_audit, confirmed_pre_send_failure=False):
    source, output = source.resolve(), output.resolve()
    if output.exists() or source == output or source in output.parents or output in source.parents:
        raise ValueError("new disjoint output required")
    old, audit, directories, hashes, pending = inspect(
        source, source_audit, confirmed_pre_send_failure
    )
    c = deepcopy(old["config"])
    c.update(
        afs_api_provider="openrouter", afs_model="openai/gpt-6-luna-pro", afs_service_tier=None
    )
    manifest = search.freeze(c, cli.sources(c) + [Path(__file__).resolve()])
    if manifest["model_hashes"] != old["model_hashes"]:
        raise ValueError("local GR00T checkpoint changed")
    output.mkdir(parents=True)
    for directory in sorted(directories):
        target = output / directory.relative_to(source)
        shutil.copytree(directory, target)
    inherited = {}
    for relative, h in hashes.items():
        target = output / relative
        if search.sha(target) != h or search.sha(source / relative) != h:
            raise ValueError("source/copy changed during transition")
        inherited[str(target)] = h
    transition = {
        "source": str(source),
        "source_manifest_sha256": search.sha(source / "manifest.json"),
        "pre_edit_source_audit": audit,
        "source_artifact_hashes": hashes,
        "old_request_path": str(pending / "request.json"),
        "old_request_sha256": search.sha(pending / "request.json"),
        "old_request_disposition": "Preserved at source; not copied/resubmitted",
        "old_transport_status": "Not sent per user-provided missing OPENAI_API_KEY traceback; "
        "absence of response alone does not establish this",
        "inherited_bootstrap_robot_attempts": len(directories),
        "old_unsent_request_intents": 1,
        "remaining_robot_attempt_cap": len(c["seeds"]) * (c["per_arm"] - c["bootstrap"]) * 2,
        "new_openrouter_request_cap": len(c["seeds"]) * (c["per_arm"] - c["bootstrap"]),
        "note": "Explicit provider/model development transition, not an independent replication. "
        "Inherited episodes count once; do not pool source and destination as new samples.",
    }
    placement.save(output / "transition.json", transition)
    manifest.update(
        mode="paired_development",
        inherited_artifacts=inherited,
        transition_sha256=search.sha(output / "transition.json"),
    )
    manifest["source_hashes"][str(output / "transition.json")] = manifest["transition_sha256"]
    placement.save(output / "manifest.json", manifest)
    (output / "manifest.sha256").write_text(search.sha(output / "manifest.json") + "\n")
    placement.save(output / "openrouter_config.json", c)
    return transition


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=BASE / "placement_wide_v1")
    parser.add_argument("--output", type=Path, default=BASE / "placement_wide_openrouter_v1")
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--confirmed-pre-send-key-error", action="store_true")
    parser.add_argument(
        "--prepare", action="store_true", help="Copy/freeze only; never runs API/robot"
    )
    args = parser.parse_args()
    if not args.prepare:
        _, _, directories, _, _ = inspect(
            args.source.resolve(), args.source_audit, args.confirmed_pre_send_key_error
        )
        print("PLAN ONLY; bootstrap copies:", len(directories), "; no API/robot execution")
        return
    transition = prepare(
        args.source, args.output, args.source_audit, args.confirmed_pre_send_key_error
    )
    print("PREPARED", args.output.resolve())
    print("Inherited robot attempts:", transition["inherited_bootstrap_robot_attempts"])
    print("Remaining robot attempts:", transition["remaining_robot_attempt_cap"])
    print("New OpenRouter request cap:", transition["new_openrouter_request_cap"])


if __name__ == "__main__":
    main()
