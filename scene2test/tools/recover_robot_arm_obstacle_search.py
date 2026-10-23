"""Versioned recovery of one proven pre-worker source-drift slot, never retry/replacement."""

import argparse
import json
import shutil
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))
import run_robot_arm_obstacle_search as cli  # noqa: E402

from robot_arm import capability, placement, search  # noqa: E402
from robot_arm import obstacle_search as experiment  # noqa: E402

BLOCKED = "seed_647/random/attempt_00001"


def recover(source, target):
    if target.exists():
        raise FileExistsError("preserve existing recovery")
    original = search.read(source / "manifest.json")
    if search.sha(source / "manifest.json") != (source / "manifest.sha256").read_text().strip():
        raise ValueError("source manifest changed")
    if original.get("mode") != experiment.VERSION or original.get("recovery"):
        raise ValueError("expected original obstacle pilot")
    design = experiment.validate(original["design"])
    c = design["experiment"]
    if c["seeds"] != [641, 647, 653] or c["per_arm"] != 4 or c["bootstrap"] != 2:
        raise ValueError("unexpected original budget")
    allowed = {
        str(PROJECT / "src/llm_afs/provider.py"),
        str(PROJECT / "src/robot_arm/obstacle_search.py"),
    }
    changed = {
        p: {"before": h, "after": search.sha(p)}
        for p, h in original["source_hashes"].items()
        if search.sha(p) != h
    }
    if not set(changed) <= allowed:
        raise ValueError("unexpected source drift")
    directories = sorted(p for p in source.glob("seed_*/*/attempt_*") if p.is_dir())
    if len(directories) != 10 or any(list(d.glob("*request.json")) for d in directories):
        raise ValueError("expected nine completed bootstrap slots and one blocked slot, zero API")
    inherited = {str(source / "manifest.json"): search.sha(source / "manifest.json")}
    for d in directories:
        rel = str(d.relative_to(source))
        value = search.read(d / "candidate.json")
        seed = int(d.parents[1].name.split("_")[1])
        index = int(d.name.split("_")[1])
        if index >= 2 or value != experiment.candidate(
            design, experiment.uniform(design, seed, index), seed, index, "uniform bootstrap"
        ):
            raise ValueError("source candidate mismatch")
        if search.read(d / "robot_intent.json") != value:
            raise ValueError("source intent mismatch")
        if rel == BLOCKED:
            if any(
                (d / name).exists()
                for name in [
                    "worker_started.json",
                    "receipt.json",
                    "physics.jsonl",
                    "trace.jsonl",
                    "initial_state.json",
                    "response.json",
                ]
            ):
                raise ValueError("blocked slot may have started; do not recover")
            if set(p.name for p in d.iterdir()) != {
                "candidate.json",
                "manifest.json",
                "robot_intent.json",
                "run.log",
            }:
                raise ValueError("unexpected blocked artifacts")
            log = (d / "run.log").read_text()
            marker = "ValueError: frozen file changed: " + str(PROJECT / "src/llm_afs/provider.py")
            if marker not in log or "return worker(root)" not in log:
                raise ValueError("missing pre-worker failure proof")
        elif experiment.receipt(d, value)["status"] != "VALID":
            raise ValueError("unexpected excluded result")
        for p in d.rglob("*"):
            if p.is_symlink():
                raise ValueError("symlink refused")
            if p.is_file():
                inherited[str(p)] = search.sha(p)
    if not (source / BLOCKED).is_dir():
        raise ValueError("missing blocked slot")
    # Same model bytes and robot sources; only documented source epochs change.
    manifest = search.freeze(c, cli.sources(c) + [Path(__file__).resolve()])
    if manifest["model_hashes"] != original["model_hashes"]:
        raise ValueError("robot model changed")
    target.mkdir(parents=True, exist_ok=False)
    excluded = {}
    for d in directories:
        rel = str(d.relative_to(source))
        dest = target / rel
        shutil.copytree(d, dest)
        for p in d.rglob("*"):
            if p.is_file() and search.sha(dest / p.relative_to(d)) != inherited[str(p)]:
                raise ValueError("copy mismatch")
        if rel == BLOCKED:
            result = {
                "status": "INCONCLUSIVE",
                "task_outcome": None,
                "reason": "preserved_pre_worker_source_drift",
                "administrative_record": True,
                "robot_executed": False,
                "original_directory": str(d),
                "claim": "Original intent consumes its slot. No retry or replacement.",
            }
            placement.save(dest / "receipt.json", result)
            placement.save(dest / "measurement.json", capability.case_measure(dest, result))
            experiment.seal(dest)
            excluded[rel] = search.sha(dest / "receipt.json")
    recovery = {
        "version": "pre-worker-drift-recovery-v1",
        "source": str(source),
        "inherited_valid": 9,
        "preserved_excluded": 1,
        "new_attempt_cap": 14,
        "remaining_afs_request_cap": 6,
        "excluded_slots": excluded,
        "source_changes": changed,
        "robot_and_model_unchanged": True,
        "comparison_limit": "Maximum AFS12/Random11 valid outcomes; equal-valid Gain remains null.",
    }
    manifest.update(
        mode=experiment.VERSION, design=design, inherited_artifacts=inherited, recovery=recovery
    )
    placement.save(target / "manifest.json", manifest)
    (target / "manifest.sha256").write_text(search.sha(target / "manifest.json") + "\n")
    placement.save(target / "recovery.json", recovery)
    return recovery


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=cli.ROOT)
    p.add_argument(
        "--output",
        type=Path,
        default=PROJECT / "experiments/robot_arm_libero/obstacle_comparison_recovery_v2",
    )
    a = p.parse_args()
    print(json.dumps(recover(a.source.resolve(), a.output.resolve()), indent=2))


if __name__ == "__main__":
    main()
