"""Offline corridor-v2 development fixtures: static maps, NOT robot outcomes.

No API calls, GPU inference, GIF or robot actions. Optional CPU G1 composition audit.
"""

import argparse
import json
from datetime import UTC, datetime
from html import escape
from pathlib import Path

from clear_path import fixture
from clear_path.contracts import CorridorFixture
from clear_path.report import plot_map
from failure_client.evaluation.goal_run_reader import _hash_file
from robot_vlm.scene_config import validate_scene

PROJECT = Path(__file__).resolve().parents[1]


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root", type=Path, default=Path("/workspace/g1_failure/runtime/corridor_previews")
    )
    parser.add_argument("--scene-config", type=Path, action="append")
    parser.add_argument("--audit-robot", action="store_true")
    parser.add_argument(
        "--groot-root", type=Path, default=Path("/workspace/g1_failure/src/GR00T-WholeBodyControl")
    )
    args = parser.parse_args(argv)
    paths = args.scene_config or [
        PROJECT / f"config/scenes/corridor_{name}.json" for name in ("wide", "narrow", "offset")
    ]
    configs = [validate_scene(json.loads(path.read_text())) for path in paths]
    if any(not isinstance(c, CorridorFixture) for c in configs):
        parser.error("only clear-path-corridor-v2 scenes are supported")
    source = None
    if args.audit_robot:
        source = args.groot_root / "decoupled_wbc/sim2mujoco/resources/robots/g1/g1_gear_wbc.xml"
    root = args.output_root.resolve() / datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    root.mkdir(parents=True, exist_ok=False)
    print(f"CORRIDOR_PREVIEW={root}", flush=True)
    sections, rows = [], []
    for i, (path, config) in enumerate(zip(paths, configs)):
        directory = root / f"scene_{i:03}"
        directory.mkdir()
        nav, graph = fixture.navigation_map(config), fixture.graph(config)
        xml = fixture.world_xml(config, source)
        with (directory / "scene.xml").open("x") as stream:
            stream.write(xml)
        write(directory / "scene_config.json", config.model_dump())
        write(directory / "scene_graph.json", graph)
        write(directory / "navigation_map.json", nav)
        if source is not None:
            import mujoco

            from clear_path import audit

            inspected = audit.inspect(source, mujoco.MjModel.from_xml_string(xml))
            write(directory / "robot_audit.json", inspected)
        plot_map(nav, directory / "map.png", config)
        row = {
            "source": str(path.resolve()),
            "directory": directory.name,
            "scene_revision": fixture.identity(config),
            "parameters": config.model_dump(),
            "box_xy_m": list(fixture.box_start(config)),
            "static_path_exists": nav["reachable"],
            "task_outcome": "NOT_EXECUTED",
            "robot_composition_audited": source is not None,
        }
        rows.append(row)
        sections.append(
            f"<section><h2>{escape(path.stem)}</h2>"
            f"<pre>{escape(json.dumps(row, indent=2, ensure_ascii=False))}</pre>"
            f"<img src='{directory.name}/map.png' alt='Static geometry preview'>"
            f"<p><a href='{directory.name}/scene_config.json'>Scene config</a> · "
            f"<a href='{directory.name}/scene_graph.json'>SceneGraph</a> · "
            f"<a href='{directory.name}/navigation_map.json'>Map</a></p></section>"
        )
    write(
        root / "summary.json",
        {
            "schema_version": "corridor-development-preview-v1",
            "api_calls": 0,
            "robot_rollouts": 0,
            "physics_steps": 0,
            "scenes": rows,
            "claim": "Static planning/asset checks only. Neither robot success nor impossibility.",
        },
    )
    with (root / "report.html").open("x") as stream:
        stream.write(
            "<!doctype html><html lang='ko'><meta charset='utf-8'>"
            "<title>Corridor development scenes</title><style>"
            "body{max-width:1100px;margin:32px auto;font-family:sans-serif}"
            "img{width:100%}pre{white-space:pre-wrap}</style><h1>통로 장면 미리보기</h1>"
            "<p>실제 로봇 실행 0회 · API 호출 0회. 그림의 선은 정적 지도 경로이며 "
            "로봇에게 제공되는 정답 경로나 실제 궤적이 아닙니다. 경로가 없어도 물체 조작을 "
            "포함한 목표 달성이 불가능하다는 뜻은 아닙니다.</p>" + "".join(sections) + "</html>"
        )
    write(
        root / "manifest.json",
        {
            "artifacts": [
                {"path": str(p.relative_to(root)), "sha256": _hash_file(p)}
                for p in sorted(root.rglob("*"))
                if p.is_file()
            ],
        },
    )
    print(f"REPORT={root / 'report.html'}", flush=True)
    return root


if __name__ == "__main__":
    main()
