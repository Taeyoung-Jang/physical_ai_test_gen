#!/usr/bin/env python3
"""Report friction or external-force intervention sweeps from Server evidence."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--server-root", type=Path, default=Path("/workspace/g1_failure/runtime/server")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/reports")
    )
    return parser.parse_args()


def _parameter(interventions: list[dict[str, Any]]) -> tuple[str, float, str]:
    for operation in interventions:
        if operation["kind"] == "dynamics.set_friction":
            return "friction", float(operation["parameters"]["coefficient"]), "coefficient"
        if operation["kind"] == "dynamics.apply_external_force":
            force = operation["parameters"]["force_n"]
            magnitude = sum(float(value) ** 2 for value in force) ** 0.5
            return "external_force", magnitude, "force (N)"
    raise ValueError("job does not contain a supported dynamics intervention")


def _records(server_root: Path, experiment_id: str) -> tuple[str, str, list[dict[str, Any]]]:
    db_path = server_root / "db/simulation_server.sqlite"
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT job_id, request_json, status, result_json FROM jobs ORDER BY submitted_at"
        ).fetchall()
    records = []
    sweep_kind = parameter_label = ""
    for job_id, request_json, status, result_json in rows:
        request = json.loads(request_json)
        if request.get("research_context", {}).get("experiment_id") != experiment_id:
            continue
        sweep_kind, value, parameter_label = _parameter(request["interventions"])
        result = json.loads(result_json) if result_json else {}
        facts = result.get("task_facts", {})
        records.append(
            {
                "parameter": value,
                "job_id": job_id,
                "status": status,
                "termination_reason": result.get("execution", {}).get("termination_reason"),
                "standing_at_end": facts.get("standing_at_end"),
                "walked_forward": facts.get("walked_forward"),
                "command_tracking_success": facts.get("command_tracking_success"),
                "forward_distance_m": facts.get("forward_distance_m"),
                "lateral_distance_m": facts.get("lateral_distance_m"),
                "minimum_base_height_m": facts.get("minimum_base_height_m"),
                "maximum_abs_roll_rad": facts.get("maximum_abs_roll_rad"),
                "forward_velocity_rmse_mps": facts.get("forward_velocity_rmse_mps"),
                "foot_contact_slip_rms_mps": facts.get("foot_contact_slip_rms_mps"),
                "execution_provider": result.get("reproduction", {})
                .get("controller", {})
                .get("execution_provider"),
            }
        )
    if not records:
        raise SystemExit(f"no jobs found for experiment {experiment_id!r}")
    return sweep_kind, parameter_label, sorted(records, key=lambda item: item["parameter"])


def _csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _plot(path: Path, label: str, records: list[dict[str, Any]]) -> None:
    valid = [record for record in records if record["status"] == "SUCCEEDED"]
    x = [record["parameter"] for record in valid]
    figure, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    panels = (
        ("minimum_base_height_m", "Minimum base height (m)"),
        ("forward_velocity_rmse_mps", "Forward velocity RMSE (m/s)"),
        ("foot_contact_slip_rms_mps", "Foot contact slip RMS (m/s)"),
        ("lateral_distance_m", "Lateral displacement (m)"),
    )
    for axis, (key, title) in zip(axes.flat, panels, strict=True):
        axis.plot(x, [record[key] for record in valid], marker="o")
        axis.set_xlabel(label)
        axis.set_title(title)
        axis.grid(alpha=0.3)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _markdown(
    path: Path, experiment_id: str, kind: str, label: str, records: list[dict[str, Any]]
) -> None:
    failures = [
        record
        for record in records
        if record["standing_at_end"] is False
        or record["walked_forward"] is False
        or record["command_tracking_success"] is False
    ]
    invalid = [record for record in records if record["status"] != "SUCCEEDED"]
    lines = [
        f"# {experiment_id}",
        "",
        f"- Sweep type: `{kind}`",
        f"- Jobs: {len(records)}",
        f"- Research failures: {len(failures)}",
        f"- Infrastructure-invalid jobs: {len(invalid)}",
        "",
        f"| {label} | 상태 | standing | tracking | 최저 높이 | 전진 거리 | slip RMS | 종료 사유 |",
        "|---:|---|---|---|---:|---:|---:|---|",
    ]
    for record in records:

        def number(key: str) -> str:
            value = record[key]
            return "—" if value is None else f"{value:.4f}"

        lines.append(
            f"| {record['parameter']:.3f} | {record['status']} | "
            f"{record['standing_at_end']} | {record['command_tracking_success']} | "
            f"{number('minimum_base_height_m')} | {number('forward_distance_m')} | "
            f"{number('foot_contact_slip_rms_mps')} | {record['termination_reason']} |"
        )
    lines.extend(["", "![Dynamics sweep metrics](metrics.png)", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = _args()
    kind, label, records = _records(args.server_root, args.experiment_id)
    output = args.output_root / args.experiment_id
    output.mkdir(parents=True, exist_ok=True)
    _csv(output / "runs.csv", records)
    (output / "summary.json").write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _plot(output / "metrics.png", label, records)
    _markdown(output / "report.md", args.experiment_id, kind, label, records)
    print(output)


if __name__ == "__main__":
    main()
