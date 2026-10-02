"""Non-overwriting offline domain audit export, separate from observed metrics."""

import csv
import hashlib
import json
from html import escape
from pathlib import Path

from robot_vlm.task_outcome import digest


def write_domain_audit(output, audit):
    payload = {k: v for k, v in audit.items() if k != "audit_sha256"}
    if audit.get("audit_sha256") != digest(payload):
        raise ValueError("domain audit digest mismatch")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    columns = ("family", "rule_status", "scene_control_status", "observed_status", "gap")
    with (output / "families.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(audit["families"])
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(row[k]))}</td>" for k in columns) + "</tr>"
        for row in audit["families"]
    )
    readiness = audit["target_readiness"]
    initial = audit["initial_goal_occupancy"]
    envelope_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{escape(str(row[k]))}</td>"
            for k in ("object_id", "dynamic", "xy_envelope_m", "goal_disk_separation_lower_bound_m")
        )
        + "</tr>"
        for row in initial["envelopes"]
    )
    notes = "".join(f"<li>{escape(note)}</li>" for note in audit["limits"])
    priorities = "".join(
        f"<li>{escape(p['id'])}: {escape(p['reason'])} ({escape(p['kind'])})</li>"
        for p in audit["priorities"]
    )
    html = (
        '<!doctype html><html lang="ko"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>실패 유형과 장면 도메인 지원 감사</title>"
        "<style>body{font:16px system-ui;max-width:1150px;margin:2rem auto;padding:0 1rem;"
        "line-height:1.5}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;"
        "padding:.55rem;text-align:left;overflow-wrap:anywhere}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere}.scroll{overflow-x:auto}</style>"
        "<h1>실패 유형과 장면 도메인 지원 감사</h1>"
        "<p>규칙 구현, 장면 제어, 실제 발견은 서로 다른 항목입니다. "
        "이 보고서는 로봇을 실행하거나 성공·실패를 판정하지 않습니다.</p>"
        f"<p>도메인: {escape(audit['scene_schema'])} · 환경 축: {audit['axis_count']}</p>"
        f"<p>Operational 규칙 {readiness['implemented_rule_count']}개 / "
        f"전체 유형 {readiness['total_family_count']}개. 목표: "
        f"{readiness['target_family_count']}종. 실제 발견 Coverage: 미측정.</p>"
        '<p><a href="audit.json">JSON과 소스 해시</a> · '
        '<a href="families.csv">유형별 CSV</a></p>'
        '<h2>유형별 연결 상태</h2><div class="scroll"><table><tr>'
        + "".join(f"<th>{escape(c)}</th>" for c in columns)
        + "</tr>"
        + rows
        + "</table></div>"
        "<h2>초기 목표 영역 기하 점검</h2>"
        f"<p>{escape(initial['status'])}. 현재 허용 범위의 보수적인 물체 영역과 "
        "목표 원 사이의 분리 거리 하한입니다. 이후 로봇이 상자를 움직인 상태는 미확인입니다.</p>"
        '<div class="scroll"><table><tr><th>물체</th><th>동적</th><th>XY envelope m</th>'
        "<th>목표 원과 거리 하한 m</th></tr>"
        + envelope_rows
        + "</table></div>"
        + (
            "<h3>실제로 구성한 초기 배치 예제</h3>"
            "<p>이 예제의 점유 여부는 기하 상태이며 목표 성공·실패가 아닙니다.</p><pre>"
            + escape(json.dumps(initial["constructive_examples"], indent=2, ensure_ascii=False))
            + "</pre>"
            if initial.get("constructive_examples")
            else ""
        )
        + "<h2>정적 지도 확인 예제</h2>"
        "<p>경로 유무는 로봇 목표 결과나 전신 불가능성 판정이 아닙니다.</p>"
        "<pre>"
        + escape(json.dumps(audit["static_map_probes"], indent=2, ensure_ascii=False))
        + "</pre><h2>후속 개발 제안</h2><ol>"
        + priorities
        + "</ol>"
        "<h2>검증 범위와 한계</h2><ul>" + notes + "</ul></html>"
    )
    (output / "report.html").write_text(html, encoding="utf-8")
    files = ("audit.json", "families.csv", "report.html")
    manifest = {
        "schema_version": "domain-audit-export-v1",
        "audit_sha256": audit["audit_sha256"],
        "files": {name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in files},
        "claim": "Derived offline report, not a robot rollout manifest",
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output / "report.html"
