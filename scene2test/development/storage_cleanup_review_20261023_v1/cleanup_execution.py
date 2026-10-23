"""Apply only user-approved, unchanged old humanoid raw-file entries; no tree removal."""

import argparse
import csv
import fcntl
import hashlib
import json
import os
import re
import stat
import time
from contextlib import ExitStack
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = {"contacts.jsonl", "states.jsonl", "human_motion.jsonl", "events.jsonl",
       "state_trajectory.jsonl", "synthetic_trace.jsonl"}
VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif"}
ACTIVE = {"run_robot_goal_agent.py", "run_paired_discovery.py", "run_afs_autonomous.py",
          "run_behavior_regression.py", "run_factor_calibration.py", "run_goal_clearance_control.py",
          "run_random_environment.py", "run_afs_benchmark.py", "run_afs_contrast.py",
          "render_labeled_humanoid.py", "run_independent_discovery.py"}


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def signature(path):
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(f"not a regular file: {path}")
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def raw_candidate(row):
    p = Path(row["path"])
    return row["action"] == "candidate_delete" and (
        p.name in RAW or re.fullmatch(r"camera_[0-9]+\.png", p.name) is not None)


def active_check():
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit() or int(proc.name) == os.getpid():
            continue
        try:
            args = (proc / "cmdline").read_bytes().split(b"\0")
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
        if any(Path(os.fsdecode(arg)).name in ACTIVE for arg in args if arg):
            raise RuntimeError(f"humanoid runner active, abort cleanup (PID {proc.name})")


def regular_files(root):
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        for name in files:
            p = Path(parent) / name
            if not p.is_symlink():
                yield p


def run(apply=False):
    plan = json.loads((HERE / "summary.json").read_text())
    rows = list(csv.DictReader((HERE / "files.csv").open()))
    allowed = {Path(p) for p in plan["roots"]}
    final = Path(plan["protected_final_campaign"])
    control = Path(plan["protected_reference_control"])
    if final.name != "paired_crossing_matched_local_20261023_v1":
        raise ValueError("unexpected protected final campaign")
    if any(final.is_relative_to(r) or control.is_relative_to(r) for r in allowed):
        raise ValueError("approved roots overlap protected experiments")
    selected, retained = [], []
    parents = {}
    for row_index, row in enumerate(rows):
        if row_index % 2000 == 0:
            print("INVENTORY_CHECK_PROGRESS", row_index, len(rows), flush=True)
        p, root = Path(row["path"]), Path(row["root"])
        if root not in allowed or not p.is_absolute() or not p.is_relative_to(root):
            raise ValueError("inventory path outside approved roots")
        if p.parent not in parents:
            parents[p.parent] = p.parent.resolve() == p.parent
        if not parents[p.parent] or p.is_symlink():
            raise ValueError("symlink path in inventory")
        if raw_candidate(row):
            if p.suffix.lower() in VIDEO or final in p.parents or control in p.parents:
                raise ValueError("protected file selected")
            expected = [int(row[k]) for k in ("device", "inode", "bytes", "mtime_ns")]
            if signature(p) != expected:
                raise ValueError(f"changed since approved inventory: {p}")
            if p.stat().st_nlink > 1:
                retained.append(p)
            else:
                selected.append((p, root, expected, int(row["allocated_bytes"])))
        else:
            retained.append(p)
    if len({p for p, *_ in selected}) != len(selected):
        raise ValueError("duplicate deletion entries")
    active_check()
    summary = {"selected_files": len(selected),
               "selected_logical_bytes": sum(s[2] for _, _, s, _ in selected),
               "selected_allocated_bytes": sum(b for _, _, _, b in selected),
               "additional_candidate_files_preserved": sum(
                   r["action"] == "candidate_delete" and not raw_candidate(r) for r in rows),
               "final_campaign_preserved_entirely": str(final),
               "reference_control_preserved_entirely": str(control),
               "policy": "Only approved old raw contact/state/motion/event traces and camera frames",
               "plan_csv_sha256": sha(HERE / "files.csv")}
    print("PREFLIGHT " + json.dumps(summary), flush=True)
    if not apply:
        return
    if (HERE / "execution_started.json").exists():
        raise RuntimeError("cleanup already started; inspect journal instead of repeating")
    with ExitStack() as stack:
        lock_paths = sorted({p for p in retained if p.name.endswith(".lock")} |
                            {p for p in regular_files(final) if p.name.endswith(".lock")})
        for p in lock_paths:
            stream = stack.enter_context(p.open("rb"))
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        active_check()
        print("LOCKS_ACQUIRED", len(lock_paths), flush=True)
        protected_files = set(retained) | set(regular_files(final)) | set(regular_files(control))
        before = {str(p): signature(p) for p in protected_files}
        hashed_paths = sorted({p for p in protected_files if p.suffix.lower() in VIDEO} |
                              set(regular_files(final)) | set(regular_files(control)))
        print("HASHING_PROTECTED_FILES", len(hashed_paths), flush=True)
        hashes = {}
        for i, p in enumerate(hashed_paths):
            hashes[str(p)] = sha(p)
            if (i + 1) % 250 == 0:
                print("PROTECTED_HASH_PROGRESS", i + 1, flush=True)
        (HERE / "protected_before.json").write_text(json.dumps(
            {"signatures": before, "sha256": hashes}, indent=2) + "\n")
        started = time.time()
        (HERE / "execution_started.json").write_text(json.dumps(
            summary | {"started_unix_s": started}, indent=2) + "\n")
        deleted_bytes = allocated = count = 0
        per_root = {}
        print("DELETING_APPROVED_RAW_FILES", flush=True)
        with (HERE / "deletion_journal.jsonl").open("x") as journal:
            for p, root, expected, blocks in selected:
                if signature(p) != expected or p.parent.resolve() != p.parent:
                    raise ValueError(f"file changed during cleanup: {p}")
                p.unlink()
                count += 1
                deleted_bytes += expected[2]
                allocated += blocks
                key = str(root)
                per_root.setdefault(key, {"files": 0, "bytes": 0})
                per_root[key]["files"] += 1
                per_root[key]["bytes"] += expected[2]
                journal.write(json.dumps({"path": str(p), "bytes": expected[2],
                                          "status": "deleted"}) + "\n")
                if count % 250 == 0:
                    journal.flush()
                    print("DELETE_PROGRESS", count, deleted_bytes, flush=True)
        print("VERIFYING_PRESERVED_FILES", len(before), flush=True)
        for name, expected in before.items():
            if signature(Path(name)) != expected:
                raise ValueError(f"preserved file signature changed: {name}")
        for i, (name, expected) in enumerate(hashes.items()):
            if sha(Path(name)) != expected:
                raise ValueError(f"preserved file content changed: {name}")
            if (i + 1) % 250 == 0:
                print("AFTER_HASH_PROGRESS", i + 1, flush=True)
        if any(p.exists() for p, *_ in selected):
            raise ValueError("some selected files remain")
        receipt = summary | {"status": "COMPLETE", "deleted_files": count,
                             "deleted_logical_bytes": deleted_bytes,
                             "deleted_allocated_bytes": allocated,
                             "per_root": per_root, "preserved_file_signatures_verified": len(before),
                             "preserved_content_hashes_verified": len(hashes),
                             "preserved_videos": sum(Path(n).suffix.lower() in VIDEO for n in hashes),
                             "elapsed_s": time.time() - started,
                             "historical_full_trace_revalidation_available": False,
                             "final_experiment_raw_evidence_preserved": True}
        (HERE / "execution_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("COMPLETE " + json.dumps({k: v for k, v in receipt.items() if k != "per_root"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    run(parser.parse_args().apply)
