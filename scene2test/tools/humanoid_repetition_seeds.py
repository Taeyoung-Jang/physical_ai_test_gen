"""Assign three random environment-search seeds once, then preserve them on resume."""

import argparse
import fcntl
import json
import secrets
from pathlib import Path

from failure_client.experiments.local_goal_adapter import atomic_json
from llm_afs.behavior import digest


def validate(seeds):
    if (
        not isinstance(seeds, list)
        or len(seeds) != 3
        or len(set(seeds)) != 3
        or any(type(s) is not int or not 1 <= s <= 2147483647 for s in seeds)
    ):
        raise ValueError("three distinct integer seeds in 1..2147483647 required")
    return seeds


def read(root):
    root = Path(root)
    bundle, assignment = root / "repetitions.json", root / "seed_assignment.json"
    seeds = None
    if bundle.exists():
        wrapped = json.loads(bundle.read_text())
        if wrapped["sha256"] != digest(wrapped["value"]):
            raise ValueError("repetition bundle digest changed")
        rows = wrapped["value"]["repetitions"]
        seeds = validate([r["seed"] for r in rows])
        if any(r["directory"] != f"seed_{r['seed']}" for r in rows):
            raise ValueError("seed directory binding differs")
    if assignment.exists():
        wrapped = json.loads(assignment.read_text())
        if wrapped["sha256"] != digest(wrapped["value"]):
            raise ValueError("seed assignment digest changed")
        selected = validate(wrapped["value"]["seeds"])
        if seeds is not None and seeds != selected:
            raise ValueError("seed assignment and frozen bundle differ")
        seeds = selected
    if seeds is None:
        raise ValueError("no saved seed assignment or prepared repetition bundle")
    return seeds


def assign(root, *, randbelow=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".seed_assignment.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _assign_locked(root, randbelow=randbelow)


def _assign_locked(root, *, randbelow=None):
    root = Path(root)
    if (root / "seed_assignment.json").exists() or (root / "repetitions.json").exists():
        return read(root)
    if list(root.glob("seed_*")):
        raise ValueError("existing partial campaigns without saved seeds; never reroll")
    rng = randbelow or secrets.randbelow
    seeds = []
    for _ in range(100):
        candidate = rng(2147483647) + 1
        if candidate not in seeds:
            seeds.append(candidate)
        if len(seeds) == 3:
            break
    validate(seeds)
    value = {
        "schema_version": "random-once-repetition-seeds-v1",
        "seeds": seeds,
        "selection": "OS randomness, unique seeds, no outcome filtering",
        "resume": "keep stored seeds; same seed shared by AFS and Random",
    }
    atomic_json(root / "seed_assignment.json", {"value": value, "sha256": digest(value)})
    return seeds


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--read", action="store_true")
    args = p.parse_args()
    seeds = read(args.root) if args.read else assign(args.root)
    if args.read:
        print("\n".join(map(str, seeds)))
    else:
        print("REPETITION_SEEDS=" + json.dumps(seeds), flush=True)
