"""Offline report evidence snapshots and media inventory. No API/robot or source edits."""

import argparse
import csv
import hashlib
import html
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

RUNTIME = Path("/workspace/g1_failure/runtime")
TRAJECTORY = RUNTIME / "trajectory_feedback/20261019T134446_66195"
STANDARD = RUNTIME / "behavior_regression/sol_standard_20261020_v1"
LUNA = RUNTIME / "behavior_regression/luna_standard_occupied_20261020_v1"


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def table(path, rows, fields):
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def inventory(runtime):
    runtime = Path(runtime).resolve()
    proc = subprocess.run(
        [
            "rg",
            "--files",
            "--hidden",
            "--no-ignore",
            str(runtime),
            "-g",
            "protocol.json",
            "-g",
            "*.mp4",
            "-g",
            "*.gif",
            "-g",
            "*.webm",
            "-g",
            "*.avi",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        raise ValueError("runtime inventory failed")
    paths = [
        Path(p)
        for p in proc.stdout.splitlines()
        if not Path(p).is_relative_to(runtime / "report_submission")
    ]
    media_counts = {
        ext: sum(p.suffix.lower() == ext for p in paths)
        for ext in (".mp4", ".gif", ".webm", ".avi")
    }
    rows, errors = [], []
    for path in sorted(p for p in paths if p.name == "protocol.json"):
        # Evidence copies in report bundles are not additional simulation runs.
        parts = path.relative_to(runtime).parts
        if "reports" in parts or ("memory", "evidence") in zip(parts, parts[1:]):
            continue
        try:
            protocol = read(path)
        except (ValueError, OSError):
            errors.append(str(path))
            continue
        schema = str(protocol.get("schema_version", ""))
        if not schema.startswith(("robot-goal-agent-", "robot-vlm-loop-")):
            continue
        root = path.parent
        try:
            result = read(root / "result.json") if (root / "result.json").exists() else {}
        except (ValueError, OSError):
            result = {}
            errors.append(str(root / "result.json"))
        videos = sorted(
            p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"
        )
        gifs = sorted(p.name for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".gif")
        rows.append(
            {
                "source": str(root),
                "schema": schema,
                "result_present": (root / "result.json").is_file(),
                "outcome": result.get("task_outcome", "UNAVAILABLE"),
                "reason": result.get("reason", ""),
                "mp4_present": bool(videos),
                "gif_present": bool(gifs),
                "mp4_files": ";".join(videos),
                "gif_files": ";".join(gifs),
            }
        )
    return {
        "scope": (
            "Original robot-goal-agent and robot-vlm-loop protocol directories, "
            "excluding report/memory evidence copies; not every simulator type"
        ),
        "media_check": "File presence only; not full decode or independent-episode counts",
        "runtime_media_counts": media_counts,
        "archive_count": len(rows),
        "with_mp4": sum(r["mp4_present"] for r in rows),
        "without_mp4": sum(not r["mp4_present"] for r in rows),
        "with_gif": sum(r["gif_present"] for r in rows),
        "read_errors": errors,
        "archives": rows,
    }


def latest_report(root):
    reports = sorted(Path(root).glob("reports/*/manifest.json"))
    if not reports:
        raise ValueError(f"No immutable report snapshot: {root}")
    return reports[-1].parent


def selections():
    return [
        ("development_trajectory", TRAJECTORY / "afs/attempts"),
        ("development_control", TRAJECTORY / "control"),
        (
            "normal_example",
            RUNTIME
            / "afs_autonomous/20261018T160156_325966Z_numeric_recovery"
            / "attempts/attempt_00002/rollout",
        ),
        ("sol_flex_excluded", RUNTIME / "behavior_regression/sol_flex_20261020_v1/attempts"),
        ("sol_standard_pass", STANDARD / "pass/attempts"),
        ("sol_standard_safety", STANDARD / "safety/attempts"),
        ("sol_standard_occupied", STANDARD / "occupied/attempts"),
        ("luna_standard_occupied", LUNA / "attempts"),
        ("report_development", TRAJECTORY / "afs/reports/20261019T152220_178774Z"),
        (
            "report_system_twelve_retrospective",
            RUNTIME / "system_failure_reanalysis/20261019T155051_917992Z",
        ),
        ("report_sol_pass", latest_report(STANDARD / "pass")),
        ("report_sol_safety", latest_report(STANDARD / "safety")),
        ("report_sol_occupied", latest_report(STANDARD / "occupied")),
        ("report_luna_occupied", latest_report(LUNA)),
    ]


def verify_manifest(directory):
    path = Path(directory) / "manifest.json"
    if not path.is_file():
        return
    for entry in read(path).get("artifacts", []):
        name = Path(entry["path"])
        target = (path.parent / name).resolve()
        if (
            name.is_absolute()
            or not target.is_relative_to(path.parent.resolve())
            or sha(target) != entry["sha256"]
        ):
            raise ValueError(f"Source manifest failed: {path}: {name}")


def copy_group(source, destination, output):
    source, destination = Path(source).resolve(), Path(destination)
    if not source.is_dir():
        raise ValueError(f"Source missing: {source}")
    manifests = list(source.rglob("manifest.json"))
    for manifest in manifests:
        verify_manifest(manifest.parent)
    rows = []
    for path in sorted(source.rglob("*")):
        if path.is_symlink():
            raise ValueError(f"Symlink not admitted: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        before = sha(path)
        shutil.copyfile(path, target)
        if sha(target) != before or sha(path) != before:
            raise ValueError(f"Source changed or copy failed: {path}")
        rows.append(
            {
                "source": str(path),
                "copy": str(target.relative_to(output)),
                "sha256": before,
                "bytes": target.stat().st_size,
            }
        )
    return rows


def probe(path):
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type,width,height",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return {
        "readable_metadata": proc.returncode == 0,
        "metadata": json.loads(proc.stdout) if proc.returncode == 0 else None,
        "error": proc.stderr[:500] if proc.returncode else None,
        "validation": "container metadata only, not full decode",
    }


def export(output, sources, audit):
    output = Path(output).resolve()
    if output.exists() or any(
        output.is_relative_to(Path(s).resolve()) or Path(s).resolve().is_relative_to(output)
        for _, s in sources
    ):
        raise ValueError("output must be new and separate from every source")
    output.mkdir(parents=True, exist_ok=False)
    copied, videos = [], []
    for name, source in sources:
        print(f"COPY={name}", flush=True)
        copied.extend(copy_group(source, output / "evidence" / name, output))
    # All original/copy hashes are verified before creating derived indexes.
    for row in copied:
        if sha(row["source"]) != row["sha256"]:
            raise ValueError("original changed during export")
        if Path(row["copy"]).suffix.lower() == ".mp4":
            videos.append(
                {"source": row["source"], "copy": row["copy"], **probe(output / row["copy"])}
            )
    save(output / "runtime_media_inventory.json", audit)
    table(
        output / "runtime_media_inventory.csv",
        audit["archives"],
        [
            "source",
            "schema",
            "result_present",
            "outcome",
            "reason",
            "mp4_present",
            "gif_present",
            "mp4_files",
            "gif_files",
        ],
    )
    save(output / "selected_videos.json", videos)
    table(output / "sources.csv", copied, ["source", "copy", "sha256", "bytes"])
    records = []
    for row in copied:
        if Path(row["copy"]).name != "attempts.json":
            continue
        for attempt in read(output / row["copy"]):
            episode = attempt.get("episode", {})
            records.append(
                {
                    "report_group": Path(row["copy"]).parts[1],
                    "attempt": attempt["id"],
                    "source": episode.get("source", {}).get("path"),
                    "status": episode.get("status"),
                    "outcome": episode.get("task_outcome"),
                    "primary_family": (episode.get("attribution") or {}).get("primary_family"),
                    "evidence_id": episode.get("evidence_id"),
                    "condition_id": episode.get("condition_id"),
                    "termination_reason": episode.get("termination_reason"),
                }
            )
    save(output / "report_records.json", records)
    table(
        output / "report_records.csv",
        records,
        [
            "report_group",
            "attempt",
            "source",
            "status",
            "outcome",
            "primary_family",
            "evidence_id",
            "condition_id",
            "termination_reason",
        ],
    )
    limits = [
        "Different groups/conditions must NOT be pooled for FDR or Gain",
        "The twelve-family report is retrospective, not prospective target achievement",
        "Interrupted/incomplete artifacts are retained, never promoted to VALID",
        "Archived HTML retains original references; this is a local evidence snapshot, "
        "not a fully portable replay package",
        "Video presence/container metadata does not establish full playback integrity",
    ]
    links = [
        (str((Path("evidence") / name / "report.html")), name)
        for name, _ in sources
        if name.startswith("report_")
    ]
    page = (
        "<!doctype html><meta charset='utf-8'><title>Submission evidence</title>"
        "<h1>Report evidence snapshot</h1>"
    )
    page += (
        "<ul>"
        + "".join(f"<li>{html.escape(line)}</li>" for line in limits)
        + "</ul><h2>Reports</h2><ul>"
    )
    page += "".join(
        f'<li><a href="{html.escape(path, quote=True)}">{html.escape(name)}</a></li>'
        for path, name in links
    )
    page += "</ul><h2>Selected videos</h2><ul>"
    page += "".join(
        f'<li><a href="{html.escape(v["copy"], quote=True)}">{html.escape(v["copy"])}</a>'
        f" — metadata readable: {v['readable_metadata']}</li>"
        for v in videos
    )
    (output / "index.html").write_text(page + "</ul>")
    files = [
        {"path": str(p.relative_to(output)), "sha256": sha(p), "bytes": p.stat().st_size}
        for p in sorted(output.rglob("*"))
        if p.is_file()
    ]
    manifest = {
        "schema": "submission-evidence-snapshot-v1",
        "created_utc": datetime.now(UTC).isoformat(),
        "source_files": len(copied),
        "source_bytes": sum(r["bytes"] for r in copied),
        "originals_unchanged_by_export": True,
        "limits": limits,
        "artifacts": files,
    }
    save(output / "manifest.json", manifest)
    return {
        "output": str(output),
        "files": len(copied),
        "bytes": manifest["source_bytes"],
        "selected_mp4": len(videos),
        "metadata_unreadable": sum(not v["readable_metadata"] for v in videos),
        "inventory_archives": audit["archive_count"],
        "inventory_with_mp4": audit["with_mp4"],
        "inventory_without_mp4": audit["without_mp4"],
        "inventory_with_gif": audit["with_gif"],
    }


def refresh_inventory(output, runtime):
    """Refresh derived inventory only, after verifying the existing snapshot."""
    output = Path(output).resolve()
    manifest = read(output / "manifest.json")
    if manifest.get("schema") != "submission-evidence-snapshot-v1":
        raise ValueError("not a submission snapshot")
    for row in manifest["artifacts"]:
        path = (output / row["path"]).resolve()
        if not path.is_relative_to(output) or sha(path) != row["sha256"]:
            raise ValueError("snapshot changed before inventory refresh")
    audit = inventory(runtime)
    save(output / "runtime_media_inventory.json", audit)
    table(
        output / "runtime_media_inventory.csv",
        audit["archives"],
        [
            "source",
            "schema",
            "result_present",
            "outcome",
            "reason",
            "mp4_present",
            "gif_present",
            "mp4_files",
            "gif_files",
        ],
    )
    for row in manifest["artifacts"]:
        if row["path"] in {"runtime_media_inventory.json", "runtime_media_inventory.csv"}:
            path = output / row["path"]
            row.update(sha256=sha(path), bytes=path.stat().st_size)
    manifest["inventory_refreshed_utc"] = datetime.now(UTC).isoformat()
    save(output / "manifest.json", manifest)
    return {
        "output": str(output),
        "archive_count": audit["archive_count"],
        "with_mp4": audit["with_mp4"],
        "without_mp4": audit["without_mp4"],
        "with_gif": audit["with_gif"],
        "scope": audit["scope"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--refresh-inventory", action="store_true")
    args = parser.parse_args()
    result = (
        refresh_inventory(args.output, RUNTIME)
        if args.refresh_inventory
        else export(args.output, selections(), inventory(RUNTIME))
    )
    print("EXPORT=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
