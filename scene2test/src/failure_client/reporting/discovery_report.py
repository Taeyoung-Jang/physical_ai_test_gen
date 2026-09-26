"""Non-overwriting offline measurement exports; no changes to source run archives."""

from __future__ import annotations

import csv
import hashlib
import json
from html import escape
from pathlib import Path


def write_discovery_report(output: Path, campaign_id, records, metrics):
    output = output.resolve()
    if any(output.is_relative_to(Path(r.source.path).resolve()) for r in records):
        raise ValueError("output must not be inside a source run")
    output.mkdir(parents=True, exist_ok=False)
    with (output / "episodes.jsonl").open("x", encoding="utf-8") as stream:
        for record in records:
            stream.write(record.model_dump_json() + "\n")
    metrics = {"campaign_id": campaign_id, **metrics}
    (output / "metrics.json").write_text(
        json.dumps(metrics, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    columns = (
        "method",
        "seed",
        "valid_budget",
        "budget_status",
        "valid_rollouts",
        "failures",
        "successes",
        "excluded_rollouts",
        "unique_failure_scenes",
        "repeated_scene_failures",
        "failure_discovery_rate",
        "failure_diversity_coverage",
        "coverage_status",
    )
    with (output / "metrics.csv").open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(metrics["groups"])
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(g.get(c)))}</td>" for c in columns) + "</tr>"
        for g in metrics["groups"]
    )
    exclusions = "".join(
        f"<li>{escape(r.source.path)}: {escape(r.status)} / {escape(r.exclusion_reason or '')}</li>"
        for r in records
        if r.status != "VALID"
    )
    comparison = escape(json.dumps(metrics["comparison"], indent=2, ensure_ascii=False))
    notes = "".join(f"<li>{escape(note)}</li>" for note in metrics["limitations"])
    page = f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>Failure discovery measures</title>
<style>body{{font:16px system-ui;margin:2rem}}td,th{{padding:.4rem;border:1px solid #ccc}}
table{{border-collapse:collapse}}pre{{white-space:pre-wrap}}</style>
<h1>실패 발견 지표: {escape(campaign_id)}</h1>
<p>목표: FDR ≥ 30%, Random 대비 상대 향상 ≥ 20%, 실패 유형 ≥ 4/6.</p>
<p>접촉·낙상은 사건이며 목표 실패와 별개입니다. null은 미측정/계산 불가이지 0이 아닙니다.</p>
<p>현재 importer는 6종 detector를 구현하지 않았습니다. 유형 다양성은 미측정입니다.
원본을 변경하거나 로봇을 실행하지 않은 사후 보고서입니다.</p>
<table><tr>{"".join(f"<th>{escape(c)}</th>" for c in columns)}</tr>{rows}</table>
<h2>Random 대비 비교</h2><pre>{comparison}</pre>
<h2>제외 기록</h2><ul>{exclusions}</ul>
<h2>해석 범위</h2><ul>{notes}</ul>
<p><a href="metrics.json">전체 지표·곡선</a> · <a href="metrics.csv">CSV</a> ·
<a href="episodes.jsonl">실행별 측정·증거·제외 사유</a></p></html>"""
    (output / "report.html").write_text(page, encoding="utf-8")
    manifest = {
        "schema_version": "measurement-report-v1",
        "artifacts": [
            {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
            for p in sorted(output.iterdir())
            if p.is_file()
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output / "report.html"
