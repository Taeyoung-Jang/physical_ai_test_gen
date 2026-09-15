"""Summarize explicitly supplied contact probes without relabeling failures."""

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path

from clear_path.audit import sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", type=Path)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("/workspace/g1_failure/runtime/clear_path_contact_reports"),
    )
    args = parser.parse_args()
    records = []
    for run in args.runs:
        run = run.resolve()
        manifest = json.loads((run / "manifest.json").read_text())
        for item in manifest["artifacts"]:
            path = run / item["path"]
            if sha256(path) != item["sha256"] or path.stat().st_size != item["size_bytes"]:
                raise ValueError(f"artifact mismatch: {path}")
        records.append(
            {
                "run": str(run),
                "result": json.loads((run / "result.json").read_text()),
                "protocol": json.loads((run / "protocol.json").read_text()),
                "manifest_sha256": sha256(run / "manifest.json"),
            }
        )
    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    (root / "summary.json").write_text(json.dumps(records, indent=2))
    sections = []
    for rec in records:
        result, protocol = rec["result"], rec["protocol"]
        # Relative links work when runtime is served over HTTP or opened locally.
        import os

        target = html.escape(os.path.relpath(rec["run"], root), quote=True)
        sections.append(f"""
<h2>초기 y={protocol["initial_robot_y"]:+.2f}m: {result["probe_success"]}</h2>
<p>상자 x 이동 {result["box_displacement_xyz_m"][0] * 100:.2f}cm,
손 회수 {result["released"]}, 넘어짐 {result["fallen"]},
금지 접촉 {result["forbidden_contact"]}</p>
<video controls preload='metadata' width='960' src='{target}/rollout.mp4'></video>
<p><a href='{target}/rollout.gif'>GIF</a> · <a href='{target}/report.html'>상세 결과</a></p>
""")
    page = (
        """<!doctype html><html lang='ko'><meta charset='utf-8'>
<title>접촉 밀기·손 회수 검증</title><style>
body{max-width:1000px;margin:30px auto;font-family:sans-serif}video{max-width:100%}
</style><h1>접촉 밀기·손 회수 검증</h1>
<p>실제 CUDA/MuJoCo 실행. 같은 근접 상자 fixture의 초기 위치 민감도 시험입니다.
일반 성공률·통로 개방·전체 장애물 제거 과제 성공을 의미하지 않습니다.
8cm 이동 및 손 접촉 해제 기준을 사용합니다. GPT 호출 없음.</p>
"""
        + "\n".join(sections)
        + "</html>"
    )
    (root / "report.html").write_text(page)
    print(f"CONTACT_REPORT={root / 'report.html'}")


if __name__ == "__main__":
    main()
