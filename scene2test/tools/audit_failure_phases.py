"""Read-only whole-episode behavior versus existing terminal taxonomy gates.

No API, simulator, new labels, relaxed thresholds or edits to the source archive.
"""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from failure_client.evaluation.behavior_measures import analyze_behavior, verify_episode_files
from failure_client.evaluation.failure_taxonomy import HUMAN_PROFILE, PROFILE, measure_taxonomy
from failure_client.evaluation.goal_run_reader import read_goal_run
from failure_client.evaluation.research_records import RunInput


def gate_review(taxonomy, components=None):
    """Explain recorded gates only; this is NOT a second classification rule."""
    m, t = taxonomy["measurements"], taxonomy["thresholds"]
    progress, geometry = m.get("terminal_progress", {}), m.get("geometry", {})
    contacts = m.get("non_support_contacts", {})
    distances = geometry.get("terminal_base_distance_to_obstacles_m", {})
    return {
        "terminal_progress": progress,
        "collision": {
            "requires": "terminal stall AND qualifying recent navigation contact",
            "stalled": progress.get("stalled"),
            "qualifying_recent_contacts": (
                len(contacts["terminal_navigation_contacts"])
                if contacts.get("status") == "AVAILABLE"
                else None
            ),
            "contact_window_s": t["recent_contact_s"],
        },
        "obstacle_interference": {
            "requires": "terminal stall AND recent blocked tools AND obstacle proximity",
            "stalled": progress.get("stalled"),
            "recent_blocked_tools": (
                len(m["blocked_tools"])
                if "blocked_tools" in m
                and (components is None or components.get("actions") == "AVAILABLE")
                else None
            ),
            "required_blocked_tools": t["blocked_tool_count"],
            "blocked_window_s": t["blocked_tool_window_s"],
            "nearest_obstacle_m": min(distances.values()) if distances else None,
            "maximum_obstacle_distance_m": t["near_obstacle_m"],
        },
        "goal_occupied": {
            "requires": "terminal stall AND full goal disk coverage through terminal window",
            "stalled": progress.get("stalled"),
            "covering_objects": geometry.get("goal_disk_covered_through_window_by"),
        },
        "human_safety_risk": m.get("human_proximity", {"status": "UNSUPPORTED"}),
    }


def audit_run(path, *, profile=HUMAN_PROFILE):
    record = read_goal_run(RunInput(path=str(Path(path).resolve())))
    behavior = analyze_behavior(record)
    taxonomy = measure_taxonomy(record, behavior, profile=profile)
    # The importer has verified all declared artifact hashes, including excluded runs
    # with intact archives. Recheck before presenting VALID episode measurements.
    if record.status == "VALID":
        verify_episode_files(record)
    actions = [i for i in behavior.intervals if i.kind == "action_window"]
    contacts = [i for i in behavior.intervals if i.kind == "contact"]
    whole = {
        "status": behavior.status,
        "components": behavior.components,
        "action_counts": (
            dict(Counter(i.details.get("action") for i in actions))
            if behavior.components.get("actions") == "AVAILABLE"
            else None
        ),
        "action_windows": [i.model_dump(mode="json") for i in actions],
        "non_support_contact_intervals": (
            [i.model_dump(mode="json") for i in contacts if not i.details.get("support_contact")]
            if behavior.components.get("events") == "AVAILABLE"
            else None
        ),
        "warnings": behavior.warnings,
        "timing": "Observation-to-result windows include inference, not precise motion onset",
    }
    return {
        "schema_version": "failure-phase-audit-v1",
        "source": record.source.path,
        "evidence_id": record.evidence_id,
        "artifact_hashes": record.artifact_hashes,
        "status": record.status,
        "task_outcome": record.task_outcome,
        "termination_reason": record.termination_reason,
        "exclusion_reason": record.exclusion_reason,
        "existing_taxonomy": taxonomy,
        "gate_review": gate_review(taxonomy, behavior.components),
        "whole_episode": whole,
        "claim": (
            "Diagnostic review only. Whole-episode events do not satisfy terminal gates "
            "by themselves. No goal verdict, measured family, threshold or archive is changed."
        ),
    }


def write_report(output, rows):
    output = Path(output).resolve()
    roots = [Path(r["source"]).resolve() for r in rows]
    if any(output.is_relative_to(root) or root.is_relative_to(output) for root in roots):
        raise ValueError("output must be separate from source archives")
    output.mkdir(parents=True, exist_ok=False)
    data = {"schema_version": "failure-phase-audit-v1", "runs": rows}
    (output / "audit.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False)
    )
    sections = []
    for row in rows:
        sections.append(
            "<h2>"
            + escape(Path(row["source"]).parent.name)
            + " · "
            + escape(str(row["task_outcome"]))
            + "</h2><p>"
            + escape(row["source"])
            + "</p><pre>"
            + escape(json.dumps(row, indent=2, ensure_ascii=False))
            + "</pre>"
        )
    report = output / "report.html"
    report.write_text(
        '<!doctype html><meta charset="utf-8"><title>Failure phase audit</title>'
        "<h1>전체 행동과 기존 실패 유형 판정 조건</h1>"
        "<p>읽기 전용 진단입니다. 목표 판정과 실패 유형을 변경하지 않습니다.</p>"
        "<style>pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>" + "".join(sections)
    )
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="append", type=Path, required=True)
    parser.add_argument(
        "--taxonomy-profile", choices=(PROFILE, HUMAN_PROFILE), default=HUMAN_PROFILE
    )
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if len({p.resolve() for p in args.run}) != len(args.run):
        parser.error("duplicate archive input")
    rows = [audit_run(p, profile=args.taxonomy_profile) for p in args.run]
    output = args.output_dir or Path("/workspace/g1_failure/runtime/failure_phase_audit") / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    )
    report = write_report(output, rows)
    print(f"REPORT={report}")
    for row in rows:
        print(
            "PHASE_AUDIT="
            + json.dumps(
                {
                    "source": row["source"],
                    "status": row["status"],
                    "outcome": row["task_outcome"],
                    "existing_primary_family": row["existing_taxonomy"]["primary_family"],
                    "stalled": row["gate_review"]["terminal_progress"].get("stalled"),
                    "whole_episode_action_counts": row["whole_episode"]["action_counts"],
                }
            )
        )
    print("No API/robot executed; no source verdict or family assignments changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
