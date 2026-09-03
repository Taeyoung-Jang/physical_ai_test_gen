#!/usr/bin/env python3
"""Aggregate command-sweep jobs into report-ready tables and plots."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt

SERVER_ROOT = Path("/workspace/g1_failure/runtime/server")
REPORT_ROOT = Path("/workspace/g1_failure/runtime/reports")
METRIC_KEYS = (
    "forward_velocity_rmse_mps",
    "lateral_velocity_rmse_mps",
    "yaw_rate_rmse_radps",
    "maximum_abs_roll_rad",
    "maximum_abs_pitch_rad",
    "foot_contact_slip_rms_mps",
    "joint_torque_rms_nm",
    "mean_absolute_mechanical_power_w",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-prefix", required=True)
    parser.add_argument("--server-root", type=Path, default=SERVER_ROOT)
    parser.add_argument("--output-root", type=Path, default=REPORT_ROOT)
    return parser.parse_args()


def _runs(server_root: Path, prefix: str) -> list[dict[str, Any]]:
    path = server_root / "db/simulation_server.sqlite"
    with sqlite3.connect(path) as db:
        rows = db.execute(
            "SELECT job_id, request_json, status, result_json FROM jobs ORDER BY submitted_at"
        ).fetchall()
    output = []
    for job_id, request_json, status, result_json in rows:
        request = json.loads(request_json)
        context = request.get("research_context", {})
        experiment_id = context.get("experiment_id", "")
        if not experiment_id.startswith(prefix + "_"):
            continue
        result = json.loads(result_json) if result_json else {}
        facts = result.get("task_facts", {})
        parameters = request["task"]["parameters"]
        record = {
            "condition": experiment_id.removeprefix(prefix + "_"),
            "job_id": job_id,
            "seed": request["execution"]["seed"],
            "status": status,
            "standing_at_end": facts.get("standing_at_end"),
            "command_tracking_success": facts.get("command_tracking_success"),
            "execution_provider": result.get("reproduction", {})
            .get("controller", {})
            .get("execution_provider"),
            "command_x_mps": parameters.get("linear_velocity_x", 0.0),
            "command_y_mps": parameters.get("linear_velocity_y", 0.0),
            "command_yaw_radps": parameters.get("yaw_rate", 0.0),
            "forward_distance_m": facts.get("forward_distance_m"),
            "lateral_distance_m": facts.get("lateral_distance_m"),
            "heading_change_rad": facts.get("heading_change_rad"),
            "minimum_base_height_m": facts.get("minimum_base_height_m"),
        }
        record.update({key: facts.get(key) for key in METRIC_KEYS})
        output.append(record)
    return output


def _mean(records: list[dict[str, Any]], key: str) -> float:
    return statistics.fmean(float(record[key]) for record in records if record[key] is not None)


def _summaries(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    conditions = list(dict.fromkeys(run["condition"] for run in runs))
    summaries = []
    for condition in conditions:
        records = [run for run in runs if run["condition"] == condition]
        valid = [run for run in records if run["status"] == "SUCCEEDED"]
        summary = {
            "condition": condition,
            "runs": len(records),
            "valid_runs": len(valid),
            "success_rate": sum(
                run["standing_at_end"] is True and run["command_tracking_success"] is True
                for run in valid
            )
            / len(valid),
            "cuda_runs": sum(run["execution_provider"] == "CUDAExecutionProvider" for run in valid),
            "command_x_mps": valid[0]["command_x_mps"],
            "command_y_mps": valid[0]["command_y_mps"],
            "command_yaw_radps": valid[0]["command_yaw_radps"],
        }
        for key in (
            "forward_distance_m",
            "lateral_distance_m",
            "heading_change_rad",
            "minimum_base_height_m",
            *METRIC_KEYS,
        ):
            summary[f"mean_{key}"] = _mean(valid, key)
        summaries.append(summary)
    return summaries


def _write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def _plot(path: Path, summaries: list[dict[str, Any]]) -> None:
    labels = [item["condition"] for item in summaries]
    figure, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    panels = (
        ("mean_forward_velocity_rmse_mps", "Forward velocity RMSE (m/s)"),
        ("mean_yaw_rate_rmse_radps", "Yaw-rate RMSE (rad/s)"),
        ("mean_minimum_base_height_m", "Minimum base height (m)"),
        ("mean_foot_contact_slip_rms_mps", "Foot contact slip RMS (m/s)"),
    )
    for axis, (key, title) in zip(axes.flat, panels, strict=True):
        axis.bar(labels, [item[key] for item in summaries])
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=35)
        axis.grid(axis="y", alpha=0.3)
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _markdown(path: Path, prefix: str, summaries: list[dict[str, Any]]) -> None:
    lines = [
        f"# {prefix} 결과",
        "",
        f"총 {sum(item['runs'] for item in summaries)}회 GPU rollout, "
        f"{len(summaries)}개 명령 조건을 평가했다.",
        "",
        "| 조건 | 명령 (x, y, yaw) | 성공률 | 전진 거리 | 횡이동 | heading | 최저 높이 | "
        "속도 RMSE (x/y/yaw) |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in summaries:
        lines.append(
            f"| {item['condition']} | ({item['command_x_mps']:.2f}, "
            f"{item['command_y_mps']:.2f}, {item['command_yaw_radps']:.2f}) | "
            f"{item['success_rate']:.1%} | {item['mean_forward_distance_m']:.3f} | "
            f"{item['mean_lateral_distance_m']:.3f} | "
            f"{item['mean_heading_change_rad']:.3f} | "
            f"{item['mean_minimum_base_height_m']:.3f} | "
            f"{item['mean_forward_velocity_rmse_mps']:.3f} / "
            f"{item['mean_lateral_velocity_rmse_mps']:.3f} / "
            f"{item['mean_yaw_rate_rmse_radps']:.3f} |"
        )
    lines.extend(
        [
            "",
            "![Command sweep metrics](metrics.png)",
            "",
            "> 같은 조건의 반복은 현재 결정론적이므로 반복 분산이 0일 수 있다. 이 sweep은 명령",
            "> 범위의 1차 기준선이며 외란 강건성 실험과 구분한다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = _args()
    runs = _runs(args.server_root, args.experiment_prefix)
    if not runs:
        raise SystemExit(f"no jobs found for prefix {args.experiment_prefix!r}")
    summaries = _summaries(runs)
    output = args.output_root / args.experiment_prefix
    output.mkdir(parents=True, exist_ok=True)
    _write_csv(output / "runs.csv", runs)
    _write_csv(output / "conditions.csv", summaries)
    (output / "summary.json").write_text(
        json.dumps(summaries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _plot(output / "metrics.png", summaries)
    _markdown(output / "report.md", args.experiment_prefix, summaries)
    print(json.dumps({"output_dir": str(output), "conditions": summaries}, indent=2))


if __name__ == "__main__":
    main()
