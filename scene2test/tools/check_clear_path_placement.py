"""Audit an existing run and build measured maps; never launch or move a robot."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import mujoco

from clear_path import fixture, placement_preflight
from clear_path.audit import sha256
from clear_path.contracts import Fixture


def write(path, value):
    with path.open("x") as f:
        json.dump(value, f, indent=2, ensure_ascii=False, allow_nan=False)


def svg(snapshot, title):
    nav = snapshot["navigation_map"]
    blocks = []
    for row, values in enumerate(nav["blocked"]):
        for col, value in enumerate(values):
            if value:
                blocks.append(f"<rect x='{col * 5}' y='{370 - row * 5}' width='5' height='5'/>")
    path = " ".join(f"{(x + 0.1) * 100},{375 - (y + 1) * 100}" for x, y in nav["path_xy_m"])
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 820 410'>"
        f"<rect width='820' height='410' fill='white'/><g fill='#334155'>{''.join(blocks)}</g>"
        f"<polyline points='{path}' fill='none' stroke='#16a34a' stroke-width='3'/>"
        f"<text x='10' y='402' font-size='15'>{title}; path_open={nav['reachable']}</text></svg>"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run", type=Path)
    p.add_argument(
        "--output-root",
        type=Path,
        default=Path("/workspace/g1_failure/runtime/clear_path_placement_checks"),
    )
    args = p.parse_args()
    run, config = args.run.resolve(), Fixture()
    manifest = json.loads((run / "manifest.json").read_text())
    for item in manifest["artifacts"]:
        if sha256(run / item["path"]) != item["sha256"]:
            raise ValueError("source artifact mismatch")
    protocol = json.loads((run / "protocol.json").read_text())
    if protocol["fixture_revision"] != fixture.identity(config):
        raise ValueError("unsupported fixture revision")
    result = json.loads((run / "result.json").read_text())
    if result["valid_execution"] is not True:
        raise ValueError("invalid execution cannot provide trusted final state")
    model = mujoco.MjModel.from_xml_path(str(run / "scene.xml"))
    root = args.output_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    source = {
        "run": str(run),
        "result_sha256": sha256(run / "result.json"),
        "scene_xml_sha256": sha256(run / "scene.xml"),
    }
    states = []
    for version, label in enumerate(("initial", "final")):
        state = placement_preflight.snapshot(
            model, result[label + "_qpos"], config, state_version=version, source=source
        )
        states.append(state)
        write(root / f"{label}_scene_graph.json", state["scene_graph"])
        write(root / f"{label}_navigation_map.json", state["navigation_map"])
        (root / f"{label}_map.svg").write_text(svg(state, label))
    preflight = placement_preflight.direct_push_preflight(config)
    write(root / "preflight.json", preflight)
    write(
        root / "provenance.json",
        {
            **source,
            "new_physics_steps": 0,
            "api_calls": 0,
            "code_sha256": sha256(Path(placement_preflight.__file__)),
            "cli_sha256": sha256(Path(__file__)),
        },
    )
    target = os.path.relpath(run, root)
    page = f"""<!doctype html><meta charset='utf-8'><title>옆 공간 배치 사전 검사</title>
<style>body{{max-width:1000px;margin:30px auto;font-family:sans-serif}}img{{width:100%}}</style>
<h1>옆 공간 배치: 접근 사전 검사</h1>
<p>상자 남쪽 틈 {preflight["south_gap_m"]:.2f}m / 로봇 계획 여유 폭
{preflight["required_footprint_width_m"]:.2f}m. 남쪽에서 북쪽으로 정면 밀기는
현재 접근 모델에서 거부합니다. 모든 조작 전략이 불가능하다는 뜻은 아닙니다.</p>
<p>새 물리 실행 없음. 아래 지도는 원본 실행의 실제 초기/최종 상자 pose로 재생성했습니다.
회전된 상자의 보수적 AABB와 로봇 반경을 포함합니다. 검은 영역은 팽창된 금지 영역입니다.</p>
<h2>실행 전</h2><img src='initial_map.svg'>
<h2>실행 후</h2><img src='final_map.svg'>
<p>최종 통로 개방: {states[-1]["navigation_map"]["reachable"]}.
단위 밀기 성공과 통로 개방은 별개입니다.</p>
<p><a href='{target}/report.html'>원본 실제 실행 영상</a> ·
<a href='preflight.json'>접근 검사</a> · <a href='final_scene_graph.json'>최종 SceneGraph</a></p>
"""
    (root / "report.html").write_text(page)
    write(
        root / "manifest.json",
        {
            "artifacts": [
                {"path": q.name, "sha256": sha256(q)} for q in sorted(root.iterdir()) if q.is_file()
            ]
        },
    )
    print(f"PLACEMENT_CHECK={root / 'report.html'}", flush=True)
    print(
        f"PREFLIGHT={preflight['decision']}; path_open={states[-1]['navigation_map']['reachable']}"
    )


if __name__ == "__main__":
    main()
