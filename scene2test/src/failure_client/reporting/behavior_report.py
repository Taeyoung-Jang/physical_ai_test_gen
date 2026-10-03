"""Static evidence navigation: exact log references and approximate MP4 time links."""

from __future__ import annotations

import json
import os
from html import escape
from pathlib import Path
from urllib.parse import quote


def _page(title, body):
    return f"""<!doctype html><html lang="ko"><meta charset="utf-8">
<title>{escape(title)}</title><style>
body{{font:16px system-ui;max-width:1500px;margin:2rem auto;padding:0 1rem}}
table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #ccc;padding:.4rem}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere}}video{{max-width:100%}}
</style><h1>{escape(title)}</h1>{body}</html>"""


def write_behavior_report(output: Path, memory, *, include_video=False):
    rows = []
    for case in memory["cases"]:
        links = " · ".join(
            f'<a href="evidence/{eid}/index.html">{eid[:12]}</a>' for eid in case["episodes"]
        )
        rows.append(
            f'<tr><td><a href="cases/{case["case_id"]}/case.json">{case["case_id"][:12]}</a>'
            f' · <a href="cases/{case["case_id"]}/REPRODUCE.txt">재실행 조건</a></td>'
            f"<td>{escape(case['policy_origin'])}</td><td>{escape(case['role'])}</td>"
            f"<td>{case['pass_count']}</td><td>{case['fail_count']}</td><td>{links}</td></tr>"
        )
    brackets = escape(json.dumps(memory["brackets"], ensure_ascii=False, indent=2))
    exclusions = escape(json.dumps(memory["excluded"], ensure_ascii=False, indent=2))
    index = _page(
        "행동 근거와 failure memory",
        f"""
<p>목표 결과와 행동 사건을 분리합니다. primary family/인과 원인은 아직 UNKNOWN입니다.</p>
<p>회귀 실행이나 새 API 호출을 수행하지 않았습니다.
외부 로봇 코드·모델 자원은 별도 검증이 필요합니다.</p>
<table><tr><th>Case</th><th>정책 출처</th><th>분류</th><th>PASS</th><th>FAIL</th>
<th>행동 근거</th></tr>
{"".join(rows)}</table><h2>관측된 성공/실패 bracket</h2><pre>{brackets}</pre>
<p>단조성·원인·최소 perturbation의 증명이 아닙니다.
혼합된 반복 결과는 확정 경계로 쓰지 않습니다.</p>
<h2>제외 기록</h2><pre>{exclusions}</pre><a href="memory.json">전체 memory</a>""",
    )
    (output / "index.html").write_text(index, encoding="utf-8")
    for eid, item in memory["episodes"].items():
        target = output / "evidence" / eid
        record, behavior = item["record"], item["behavior"]
        video = None
        if "rollout.mp4" in record["artifact_hashes"]:
            source = (
                target / "rollout.mp4"
                if include_video
                else Path(record["source"]["path"]) / "rollout.mp4"
            )
            video = quote(os.path.relpath(source, target), safe="/")
        media = (
            f'<video controls preload="metadata" src="{video}"></video>'
            if video
            else "<p>검증된 MP4 없음.</p>"
        )
        media += (
            "<p>MP4 시각 링크는 프레임 주기 수준의 근사입니다. "
            "정확한 시각은 원본 simulation 로그를 따릅니다."
        )
        media += (
            " 영상은 bundle에 복사됐습니다.</p>"
            if include_video and video
            else " 영상은 원본 위치를 참조합니다.</p>"
        )
        preferred = [i for i in behavior["intervals"] if not i["details"].get("support_contact")]
        visible = preferred[:200]
        table = []
        for interval in visible:
            start, end = interval["start_s"], interval["end_s"]
            label = f"{start if start is not None else '?'} → {end if end is not None else '?'} s"
            if video and start is not None:
                # Pad a frame on each side; do not claim a frame-exact physics/video clock.
                fragment = f"#t={max(0, start - 1 / 12):.3f}"
                if end is not None:
                    fragment += f",{end + 1 / 12:.3f}"
                label = f'<a href="{video}{fragment}">{escape(label)}</a>'
            else:
                label = escape(label)
            refs = []
            for ref in interval["evidence"]:
                name = ref["artifact"]
                suffix = f":L{ref['first_line']}–{ref['last_line']}" if ref["first_line"] else ""
                refs.append(f'<a href="{quote(name, safe="/")}">{escape(name + suffix)}</a>')
            table.append(
                f"<tr><td>{escape(interval['kind'])}</td><td>{label}</td>"
                f"<td>{escape(interval['timing'])}, censored={interval['censored']}</td>"
                f"<td><pre>{escape(json.dumps(interval['details'], ensure_ascii=False))}</pre></td>"
                f"<td>{'<br>'.join(refs)}</td></tr>"
            )
        header = {
            "task_outcome": record["task_outcome"],
            "analysis_status": behavior["status"],
            "components": behavior["components"],
            "summary": item["summary"],
            "object_motion": behavior["object_motion"],
            "max_state_sample_gap_s": behavior["max_state_sample_gap_s"],
            "warnings": behavior["warnings"],
        }
        page = _page(
            "행동 근거 " + eid[:12],
            f"""
<a href="../../index.html">memory 목록</a>
<pre>{escape(json.dumps(header, ensure_ascii=False, indent=2))}</pre>
{media}<p>observation_window는 추론 대기를 포함하며 정확한 행동 시작 시각은 아닙니다.
도구의 success와 최초 goal 달성은 다른 항목입니다.</p>
<p>발–바닥 지지 접촉을 제외한 {len(preferred)}개 중 {len(visible)}개 표시.
전체 {len(behavior["intervals"])}개 구간·지지 접촉은
<a href="behavior.json">전체 JSON</a>에 보존합니다.</p>
<table><tr><th>사건</th><th>시간/MP4</th><th>시간 근거</th><th>측정</th><th>원본/행 번호</th></tr>
{"".join(table)}</table>""",
        )
        (target / "index.html").write_text(page, encoding="utf-8")
