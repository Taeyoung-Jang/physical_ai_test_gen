"""Offline old-six versus expanded-ten analysis; never changes source archives."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from failure_client.evaluation.expanded_taxonomy import RULES, classify_expanded
from failure_client.evaluation.failure_taxonomy import (
    HUMAN_PROFILE,
    classify_record,
    rules_for_profile,
)
from failure_client.evaluation.goal_run_reader import _hash_file, read_goal_run, read_json
from failure_client.evaluation.research_records import EXPANDED_FAMILIES, RunInput
from failure_client.reporting.discovery_metrics import calculate_discovery_metrics
from failure_client.reporting.discovery_report import write_discovery_report


def analyze(paths, output):
    paths = [Path(p).resolve() for p in paths]
    output = Path(output).resolve()
    if not paths or len(set(paths)) != len(paths):
        raise ValueError("supply distinct saved rollout paths")
    if any(output.is_relative_to(p) or p.is_relative_to(output) for p in paths):
        raise ValueError("output must be separate from all source archives")
    if output.exists():
        raise FileExistsError(output)
    original = [read_goal_run(RunInput(path=str(p))) for p in paths]
    legacy = [classify_record(r, profile=HUMAN_PROFILE) for r in original]
    expanded = [classify_expanded(r) for r in original]
    old_metrics = calculate_discovery_metrics(legacy, family_rules=rules_for_profile(HUMAN_PROFILE))
    metrics = calculate_discovery_metrics(
        expanded, family_rules=RULES, family_inventory=EXPANDED_FAMILIES
    )
    metrics["analysis_scope"] = {
        "kind": "retrospective_ten_family_reanalysis",
        "claim": "Reclassified saved observations, not a prospective AFS/Random experiment",
        "legacy_six_family_metrics": old_metrics,
        "source_goal_verdicts_unchanged": True,
    }
    metrics["limitations"].append(
        "Ten-family profile is retrospective; changes in counts reflect taxonomy, not new tests"
    )
    report = write_discovery_report(output, "expanded-ten-retrospective", expanded, metrics)
    return report, metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--run", action="append", type=Path)
    source.add_argument("--session", type=Path, help="completed autonomous session; read-only")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    paths = args.run
    if args.session:
        reports = sorted((args.session / "reports").glob("*/attempts.json"))
        if not reports:
            parser.error("session has no saved attempt report")
        report_dir = reports[-1].parent.resolve()
        for entry in read_json(report_dir / "manifest.json")["artifacts"]:
            name = Path(entry["path"])
            target = (report_dir / name).resolve()
            if (
                name.is_absolute()
                or ".." in name.parts
                or not target.is_relative_to(report_dir)
                or _hash_file(target) != entry["sha256"]
            ):
                parser.error("source report manifest verification failed")
        if read_json(report_dir / "summary.json")["status"] not in {
            "COMPLETE",
            "COMPLETE_WITH_EXCLUSIONS",
            "TARGET_NOT_REACHED",
        }:
            parser.error("session is not completed; use explicit --run for selected archives")
        paths = [
            Path(a["episode"]["source"]["path"]) for a in read_json(reports[-1]) if "episode" in a
        ]
    output = args.output_dir or Path("/workspace/g1_failure/runtime/failure_type_reanalysis") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    )
    if args.session:
        s, out = args.session.resolve(), output.resolve()
        if out.is_relative_to(s) or s.is_relative_to(out):
            parser.error("output must be separate from source session")
    report, metrics = analyze(paths, output)
    print(f"REPORT={report}")
    print("EXPANDED_SUMMARY=" + json.dumps(metrics["pooled_by_method"], ensure_ascii=False))
    print("No API, GPU, robot or source verdict changes; original six-family metrics retained.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
