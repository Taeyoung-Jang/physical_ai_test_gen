"""Verified offline system-interface taxonomy comparison; no API/robot/source edits."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.expanded_taxonomy import RULES as TEN_RULES
from failure_client.evaluation.expanded_taxonomy import classify_expanded
from failure_client.evaluation.goal_run_reader import _hash_file, read_goal_run, read_json
from failure_client.evaluation.research_records import (
    EXPANDED_FAMILIES,
    SYSTEM_FAMILIES,
    EpisodeRecord,
    RunInput,
)
from failure_client.evaluation.system_taxonomy import RULES, classify_system
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.reporting.discovery_report import write_discovery_report


def snapshot_paths(session):
    """Read an immutable report snapshot, including READY campaigns; never open its DB."""
    reports = sorted(Path(session).resolve().glob("reports/*/attempts.json"))
    if not reports:
        raise ValueError("session has no saved report snapshot")
    directory = reports[-1].parent
    manifest = read_json(directory / "manifest.json")
    verified = set()
    for entry in manifest["artifacts"]:
        name = Path(entry["path"])
        p = (directory / name).resolve()
        if (
            name.is_absolute()
            or not p.is_relative_to(directory)
            or _hash_file(p) != entry["sha256"]
        ):
            raise ValueError("report snapshot artifact changed or escaped report directory")
        verified.add(str(name))
    if not {"attempts.json", "summary.json"} <= verified:
        raise ValueError("report snapshot missing required verified artifacts")
    summary = read_json(directory / "summary.json")
    if summary.get("pending") is not None:
        raise ValueError("snapshot contains unfinished request; inspect first")
    attempts = read_json(reports[-1])
    paths = [Path(a["episode"]["source"]["path"]).resolve() for a in attempts if "episode" in a]
    for path in paths:
        if not path.is_relative_to(Path(session).resolve() / "attempts"):
            raise ValueError("snapshot includes external episode rather than new session attempts")
    for a in attempts:
        if "episode" not in a:
            continue
        saved = EpisodeRecord.model_validate(a["episode"])
        actual = read_goal_run(saved.source)
        if any(
            getattr(saved, k) != getattr(actual, k)
            for k in ("evidence_id", "artifact_hashes", "status", "task_outcome")
        ):
            raise ValueError("source episode changed since report snapshot")
    return paths


def analyze(paths, output):
    paths, output = [Path(p).resolve() for p in paths], Path(output).resolve()
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("supply distinct saved rollout archives")
    if output.exists() or any(output.is_relative_to(p) or p.is_relative_to(output) for p in paths):
        raise ValueError("new output must be disjoint from source archives")
    originals = [read_goal_run(RunInput(path=str(p))) for p in paths]
    ten = [classify_expanded(r) for r in originals]
    system = [classify_system(r) for r in originals]
    old = calculate_discovery_metrics(
        ten, family_rules=TEN_RULES, family_inventory=EXPANDED_FAMILIES
    )
    metrics = calculate_discovery_metrics(
        system, family_rules=RULES, family_inventory=SYSTEM_FAMILIES
    )
    metrics["analysis_scope"] = {
        "title": "기존 10종과 시스템 계층 관측 12종 사후 비교",
        "kind": "retrospective_system_interface_candidates",
        "claim": "New taxonomy counts, NOT improved search or prospective target achievement",
        "prospective_joint_target_achieved": False,
        "original_ten_family_metrics": old,
        "detector_source_hashes": {
            name: _hash_file(Path(__file__).resolve().parents[1] / name)
            for name in (
                "src/failure_client/evaluation/system_taxonomy.py",
                "src/failure_client/evaluation/expanded_taxonomy.py",
                "tools/reanalyze_system_failures.py",
            )
        },
        "verdicts_preserved": all(
            (a.status, a.task_outcome) == (b.status, b.task_outcome)
            for a, b in zip(originals, system)
        ),
        "primary_changes": [
            {
                "source": a.source.path,
                "old": a.attribution.primary_family if a.attribution else None,
                "new": b.attribution.primary_family if b.attribution else None,
                "layers": b.taxonomy.get("failure_layers"),
            }
            for a, b in zip(ten, system)
        ],
    }
    metrics["limitations"].append(
        "Observed interface patterns do not prove an Agent/VLA/planner/controller/robot defect"
    )
    return write_discovery_report(
        output, "system-interface-retrospective", system, metrics
    ), metrics


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", type=Path, action="append")
    source.add_argument("--session", type=Path, help="latest verified report snapshot, not live DB")
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args(argv)
    paths = snapshot_paths(args.session) if args.session else args.run
    output = args.output_dir or Path("/workspace/g1_failure/runtime/system_failure_reanalysis") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    )
    if args.session and (
        output.resolve().is_relative_to(args.session.resolve())
        or args.session.resolve().is_relative_to(output.resolve())
    ):
        p.error("output must not overlap source session")
    report, metrics = analyze(paths, output)
    print(f"REPORT={report}")
    print("SYSTEM_SUMMARY=" + json.dumps(metrics["pooled_by_method"], ensure_ascii=False))
    print("No API/GPU/robot; source outcomes/budgets unchanged; component causes unconfirmed.")


if __name__ == "__main__":
    main()
