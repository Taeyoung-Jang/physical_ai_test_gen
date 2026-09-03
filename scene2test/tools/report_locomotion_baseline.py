#!/usr/bin/env python3
"""Create JSON, CSV, and Markdown summaries for a locomotion experiment."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sqlite3
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_SERVER_ROOT = Path("/workspace/g1_failure/runtime/server")
DEFAULT_REPORT_ROOT = Path("/workspace/g1_failure/runtime/reports")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--server-root", type=Path, default=DEFAULT_SERVER_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_REPORT_ROOT)
    return parser.parse_args()


def _trajectory_min_height(job_dir: Path) -> float | None:
    path = job_dir / "state_trajectory.jsonl"
    if not path.exists():
        return None
    minimum: float | None = None
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            state = json.loads(line)
            qpos = state.get("qpos") or state.get("position")
            if qpos and len(qpos) >= 3:
                height = float(qpos[2])
                minimum = height if minimum is None else min(minimum, height)
    return minimum


def _elapsed_seconds(start: str, end: str) -> float:
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def _load_runs(server_root: Path, experiment_id: str) -> list[dict[str, Any]]:
    db_path = server_root / "db/simulation_server.sqlite"
    with sqlite3.connect(db_path) as db:
        rows = db.execute(
            "SELECT job_id, request_json, status, result_json, submitted_at, updated_at "
            "FROM jobs ORDER BY submitted_at"
        ).fetchall()
    runs: list[dict[str, Any]] = []
    for job_id, request_json, status, result_json, submitted_at, updated_at in rows:
        request = json.loads(request_json)
        if request.get("research_context", {}).get("experiment_id") != experiment_id:
            continue
        result = json.loads(result_json) if result_json else {}
        facts = result.get("task_facts", {})
        reproduction = result.get("reproduction", {})
        artifacts = result.get("artifacts", [])
        tags = request.get("research_context", {}).get("opaque_tags", [])
        repeat = next((int(tag.split(":", 1)[1]) for tag in tags if tag.startswith("repeat:")), -1)
        job_dir = server_root / "outputs/jobs" / job_id
        runs.append(
            {
                "repeat_index": repeat,
                "job_id": job_id,
                "seed": request.get("execution", {}).get("seed"),
                "job_status": status,
                "execution_status": result.get("execution", {}).get("status"),
                "termination_reason": result.get("execution", {}).get("termination_reason"),
                "standing_at_end": facts.get("standing_at_end"),
                "walked_forward": facts.get("walked_forward"),
                "forward_distance_m": facts.get("forward_distance_m"),
                "lateral_distance_m": facts.get("lateral_distance_m"),
                "final_base_height_m": facts.get("final_base_height_m"),
                "minimum_base_height_m": _trajectory_min_height(job_dir),
                "execution_provider": reproduction.get("controller", {}).get(
                    "execution_provider"
                ),
                "elapsed_wall_s": _elapsed_seconds(submitted_at, updated_at),
                "video_recorded": any(item.get("kind") == "rollout_video" for item in artifacts),
                "job_dir": str(job_dir),
            }
        )
    return sorted(runs, key=lambda item: item["repeat_index"])


def _numeric_summary(runs: list[dict[str, Any]], key: str) -> dict[str, float] | None:
    values = [float(run[key]) for run in runs if run.get(key) is not None]
    if not values:
        return None
    ordered = sorted(values)
    return {
        "mean": statistics.fmean(values),
        "stddev": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": ordered[0],
        "median": statistics.median(ordered),
        "max": ordered[-1],
    }


def _build_summary(experiment_id: str, runs: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [run for run in runs if run["execution_status"] == "SUCCEEDED"]
    successful = [
        run for run in valid if run["standing_at_end"] is True and run["walked_forward"] is True
    ]
    cuda = [run for run in valid if run["execution_provider"] == "CUDAExecutionProvider"]
    return {
        "experiment_id": experiment_id,
        "run_count": len(runs),
        "valid_run_count": len(valid),
        "successful_run_count": len(successful),
        "success_rate": len(successful) / len(valid) if valid else math.nan,
        "fall_count": sum(run["standing_at_end"] is False for run in valid),
        "cuda_run_count": len(cuda),
        "video_run_count": sum(bool(run["video_recorded"]) for run in runs),
        "metrics": {
            key: _numeric_summary(valid, key)
            for key in (
                "forward_distance_m",
                "lateral_distance_m",
                "minimum_base_height_m",
                "final_base_height_m",
                "elapsed_wall_s",
            )
        },
    }


def _write_csv(path: Path, runs: list[dict[str, Any]]) -> None:
    if not runs:
        return
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(runs[0]))
        writer.writeheader()
        writer.writerows(runs)


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def _write_markdown(path: Path, summary: dict[str, Any], runs: list[dict[str, Any]]) -> None:
    metrics = summary["metrics"]
    lines = [
        f"# {summary['experiment_id']} 결과",
        "",
        "## 요약",
        "",
        f"- 전체/유효 실행: {summary['run_count']} / {summary['valid_run_count']}",
        f"- 성공: {summary['successful_run_count']} ({summary['success_rate']:.1%})",
        f"- 낙상: {summary['fall_count']}",
        f"- CUDA 확인: {summary['cuda_run_count']}회",
        f"- 영상 생성: {summary['video_run_count']}회",
        "",
        "## 통계",
        "",
        "| 지표 | 평균 | 표준편차 | 최솟값 | 중앙값 | 최댓값 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    labels = {
        "forward_distance_m": "전진 거리 (m)",
        "lateral_distance_m": "횡방향 이동 (m)",
        "minimum_base_height_m": "최저 base 높이 (m)",
        "final_base_height_m": "최종 base 높이 (m)",
        "elapsed_wall_s": "wall time (s)",
    }
    for key, label in labels.items():
        stat = metrics[key]
        if stat:
            lines.append(
                f"| {label} | {_fmt(stat['mean'])} | {_fmt(stat['stddev'])} | "
                f"{_fmt(stat['min'])} | {_fmt(stat['median'])} | {_fmt(stat['max'])} |"
            )
    lines.extend(
        [
            "",
            "## 실행별 결과",
            "",
            "| 반복 | Job | Seed | 성공 | 전진 (m) | 횡이동 (m) | 최저 높이 (m) | GPU |",
            "|---:|---|---:|---|---:|---:|---:|---|",
        ]
    )
    for run in runs:
        success = run["standing_at_end"] is True and run["walked_forward"] is True
        lines.append(
            f"| {run['repeat_index']} | `{run['job_id']}` | {run['seed']} | {success} | "
            f"{run['forward_distance_m']:.6f} | {run['lateral_distance_m']:.6f} | "
            f"{run['minimum_base_height_m']:.6f} | {run['execution_provider']} |"
        )
    lines.extend(
        [
            "",
            "> 이 결과는 동일한 평지 scene과 단일 속도 명령의 반복성 기준선이다. 환경 변화에",
            "> 대한 강건성 또는 실제 로봇 성능으로 확대 해석하지 않는다.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = _parse_args()
    runs = _load_runs(args.server_root, args.experiment_id)
    if not runs:
        raise SystemExit(f"no jobs found for experiment {args.experiment_id!r}")
    output_dir = args.output_root / args.experiment_id
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = _build_summary(args.experiment_id, runs)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _write_csv(output_dir / "runs.csv", runs)
    _write_markdown(output_dir / "report.md", summary, runs)
    print(json.dumps({"output_dir": str(output_dir), **summary}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
