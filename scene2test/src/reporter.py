"""reporter.py — Test Result Reporter.

테스트 결과 데이터를 받아 세 가지 출력물을 생성한다.

  generate_test_table(records)         → DataFrame + CSV + Markdown
  generate_counterexample_report(records) → FAIL/BLOCKED 상세 dict 목록
  generate_comparison_report(results)  → 방법별 비교 통계 + Failure Discovery Curve 데이터
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# 판정별 색상 (Streamlit/Plotly 공통)
# ---------------------------------------------------------------------------

VERDICT_COLORS = {
    "PASS":    "#2ecc71",
    "WARN":    "#f39c12",
    "FAIL":    "#e74c3c",
    "BLOCKED": "#8e44ad",
}

VERDICT_ORDER = ["BLOCKED", "FAIL", "WARN", "PASS"]


# ---------------------------------------------------------------------------
# TestRecord dict 키 alias
# ---------------------------------------------------------------------------

def _get(rec: dict, *keys, default=None):
    for k in keys:
        if k in rec:
            return rec[k]
    return default


# ---------------------------------------------------------------------------
# 1. 테스트 결과 테이블
# ---------------------------------------------------------------------------

def generate_test_table(
    records: list[dict],
    output_dir: Optional[str] = None,
    filename_stem: str = "test_results",
) -> pd.DataFrame:
    """TestRecord 목록 → DataFrame.

    선택적으로 CSV 및 Markdown 파일로 저장한다.
    """
    rows = []
    for rec in records:
        margins = rec.get("margins", {})
        row = {
            "test_id":       rec.get("test_id", ""),
            "round":         rec.get("round_idx", 0),
            "scene_id":      rec.get("scene_id", ""),
            "verdict":       rec.get("verdict", ""),
            "failure_type":  rec.get("failure_type", ""),
            "robustness":    round(rec.get("robustness", 0.0), 4),
            "acq_score":     round(rec.get("acquisition_score", 0.0), 4),
            "elapsed_s":     rec.get("elapsed_s", 0.0),
            "reason":        rec.get("reason", ""),
            "m_reach":       round(margins.get("reach", 0.0), 4),
            "m_clearance":   round(margins.get("clearance", 0.0), 4),
            "m_collision":   round(margins.get("collision", 0.0), 4),
            "m_safety":      round(margins.get("safety", 0.0), 4),
            "m_goal":        round(margins.get("goal", 0.0), 4),
            "m_perception":  round(margins.get("perception", 0.0), 4),
        }
        rows.append(row)

    df = pd.DataFrame(rows)

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        csv_path = Path(output_dir) / f"{filename_stem}.csv"
        md_path  = Path(output_dir) / f"{filename_stem}.md"
        df.to_csv(csv_path, index=False)
        # Markdown: 핵심 컬럼만
        cols = ["test_id", "round", "verdict", "failure_type", "robustness", "reason"]
        df[cols].to_markdown(md_path, index=False)

    return df


# ---------------------------------------------------------------------------
# 2. Counterexample Report
# ---------------------------------------------------------------------------

def generate_counterexample_report(
    records: list[dict],
    output_dir: Optional[str] = None,
    filename_stem: str = "counterexample_report",
) -> list[dict]:
    """FAIL / BLOCKED 케이스의 상세 리포트를 생성한다."""
    cases = []
    for rec in records:
        verdict = rec.get("verdict", "")
        if verdict not in ("FAIL", "BLOCKED"):
            continue

        margins = rec.get("margins", {})
        binding = min(margins, key=margins.get) if margins else "unknown"

        case = {
            "test_id":        rec.get("test_id", ""),
            "scene_id":       rec.get("scene_id", ""),
            "verdict":        verdict,
            "failure_type":   rec.get("failure_type", binding),
            "robustness":     rec.get("robustness", 0.0),
            "binding_margin": binding,
            "margin_value":   margins.get(binding, 0.0),
            "margins":        margins,
            "reason":         rec.get("reason", ""),
            "recommendation": rec.get("recommendation", ""),
            "mutation_params": rec.get("mutation_params", {}),
        }
        cases.append(case)

    # robustness 오름차순 (가장 심각한 케이스 먼저)
    cases.sort(key=lambda x: x["robustness"])

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        out_path = Path(output_dir) / f"{filename_stem}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(cases, f, indent=2, ensure_ascii=False)

    return cases


# ---------------------------------------------------------------------------
# 3. Comparison Report (Failure Discovery Curve)
# ---------------------------------------------------------------------------

def generate_comparison_report(
    results: dict[str, list[dict]],
    output_dir: Optional[str] = None,
    filename_stem: str = "comparison_report",
) -> dict:
    """방법별 결과를 비교 통계 + Failure Discovery Curve 데이터로 변환한다.

    Args:
        results: {"method_name": [TestRecord dict, ...], ...}

    Returns:
        {
          "summary": DataFrame,
          "curves": {"method": {"x": [1..N], "y": [누적_fail_count], "y_types": [누적_unique_types]}},
          "methods": [str],
        }
    """
    summary_rows = []
    curves: dict[str, dict] = {}

    for method, records in results.items():
        total = len(records)
        verdicts = {"PASS": 0, "WARN": 0, "FAIL": 0, "BLOCKED": 0}
        for rec in records:
            v = rec.get("verdict", "PASS")
            verdicts[v] = verdicts.get(v, 0) + 1

        fail_blocked = verdicts["FAIL"] + verdicts["BLOCKED"]
        fdr = fail_blocked / total if total > 0 else 0.0

        unique_types: set[str] = set()
        for rec in records:
            v = rec.get("verdict", "")
            if v in ("FAIL", "BLOCKED"):
                ft = rec.get("failure_type", "")
                if ft:
                    unique_types.add(ft)

        summary_rows.append({
            "method":     method,
            "total":      total,
            "pass":       verdicts["PASS"],
            "warn":       verdicts["WARN"],
            "fail":       verdicts["FAIL"],
            "blocked":    verdicts["BLOCKED"],
            "fail_blocked": fail_blocked,
            "fdr":        round(fdr, 4),
            "unique_failure_types": len(unique_types),
            "failure_types": sorted(unique_types),
        })

        # Failure Discovery Curve: 누적 FAIL/BLOCKED count + unique types
        cum_fail = []
        cum_types = []
        seen_types: set[str] = set()
        for i, rec in enumerate(records):
            v = rec.get("verdict", "")
            if v in ("FAIL", "BLOCKED"):
                ft = rec.get("failure_type", "")
                if ft:
                    seen_types.add(ft)
            cum_fail.append(sum(1 for r in records[:i+1]
                               if r.get("verdict", "") in ("FAIL", "BLOCKED")))
            cum_types.append(len(seen_types))

        curves[method] = {
            "x":       list(range(1, total + 1)),
            "y_fail":  cum_fail,
            "y_types": cum_types,
        }

    summary_df = pd.DataFrame(summary_rows)

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        csv_path = Path(output_dir) / f"{filename_stem}.csv"
        json_path = Path(output_dir) / f"{filename_stem}.json"
        summary_df.to_csv(csv_path, index=False)
        out = {
            "summary": summary_rows,
            "curves":  curves,
        }
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)

    return {
        "summary": summary_df,
        "curves":  curves,
        "methods": list(results.keys()),
    }


# ---------------------------------------------------------------------------
# 편의 함수: search log JSON → records list
# ---------------------------------------------------------------------------

def load_records_from_log(log_path: str) -> tuple[str, list[dict]]:
    """search log JSON 파일에서 (scene_id, records) 반환."""
    with open(log_path, encoding="utf-8") as f:
        log = json.load(f)
    return log.get("scene_id", "unknown"), log.get("records", [])


def load_all_logs(log_dir: str) -> dict[str, list[dict]]:
    """log_dir 내 모든 search log JSON에서 scene별 records 수집."""
    by_scene: dict[str, list[dict]] = {}
    for p in sorted(Path(log_dir).glob("search_*.json")):
        scene_id, recs = load_records_from_log(str(p))
        if scene_id not in by_scene:
            by_scene[scene_id] = []
        by_scene[scene_id].extend(recs)
    return by_scene


# ---------------------------------------------------------------------------
# LAM-Guided 리포트 (확장)
# ---------------------------------------------------------------------------

def generate_vulnerability_summary(
    profile: dict,
    output_dir: Optional[str] = None,
    filename_stem: str = "vulnerability_summary",
) -> str:
    """VulnerabilityProfile dict → markdown 요약."""
    scores = profile.get("scores", {})
    fams = profile.get("recommended_families", [])
    lines = ["# LAM Vulnerability Profile", ""]
    lines.append(f"- scene: `{profile.get('scene_id', '')}`")
    lines.append("")
    lines.append("## 취약성 점수 (높을수록 약함)")
    for axis, val in sorted(scores.items(), key=lambda x: -x[1]):
        bar = "█" * int(round(val * 20))
        lines.append(f"- {axis:24s} {val:5.2f}  {bar}")
    lines.append("")
    lines.append("## 추천 Failure Families")
    for i, f in enumerate(fams, 1):
        lines.append(f"{i}. {f}")
    md = "\n".join(lines) + "\n"
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / f"{filename_stem}.md").write_text(md, encoding="utf-8")
    return md


def generate_counterexample_table(
    records: list[dict],
    output_dir: Optional[str] = None,
    filename_stem: str = "counterexample_table",
) -> pd.DataFrame:
    """LAM-guided counterexample 목록 → DataFrame (+CSV).

    레코드 키: case_id, family, verdict, failure_types, selected_obj_id,
    expected_obj_id, reason 등.
    """
    rows = []
    for rec in records:
        rows.append({
            "counterexample_id": rec.get("counterexample_id", ""),
            "case_id":      rec.get("case_id", ""),
            "family":       rec.get("family", ""),
            "verdict":      rec.get("verdict", ""),
            "failure_types": ",".join(rec.get("failure_types", [])),
            "expected":     rec.get("expected_obj_id", ""),
            "selected":     rec.get("selected_obj_id", ""),
            "reason":       rec.get("reason", ""),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        order = {v: i for i, v in enumerate(VERDICT_ORDER)}
        df = df.sort_values(by="verdict", key=lambda s: s.map(lambda v: order.get(v, 99)))
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        df.to_csv(Path(output_dir) / f"{filename_stem}.csv", index=False)
    return df


def generate_boundary_report(
    boundaries: list[dict],
    output_dir: Optional[str] = None,
    filename_stem: str = "boundary_report",
) -> str:
    """BoundaryResult dict 목록 → markdown (최소 perturbation 경계)."""
    lines = ["# Minimum Perturbation Boundary", ""]
    if not boundaries:
        lines.append("_경계 탐색 결과 없음._")
    for b in boundaries:
        lines.append(f"## {b.get('family', '')}")
        lines.append(f"- parameter: `{b.get('param_name', '')}`")
        lines.append(f"- FAIL ≤ {b.get('fail_value', 0):.3f} m / "
                     f"PASS ≥ {b.get('pass_value', 0):.3f} m")
        lines.append(f"- 추정 경계: **{b.get('boundary', 0):.3f} m**  "
                     f"(iters={b.get('iters', 0)})")
        if b.get("note"):
            lines.append(f"- {b['note']}")
        lines.append("")
    md = "\n".join(lines) + "\n"
    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / f"{filename_stem}.md").write_text(md, encoding="utf-8")
    return md
