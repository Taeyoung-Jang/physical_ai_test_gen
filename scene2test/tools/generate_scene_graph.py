"""generate_scene_graph.py — Stage 1: 임의의 3D scene 입력에서 SceneGraph를 생성한다.

`--source`는 세 가지를 모두 받는다 (scene3d.sources.detect_source_kind가 판별):
  - HM3D 데이터셋 scene id (예: "00800")
  - 임의의 mesh 파일 경로 (.glb/.gltf/.obj/.ply)
  - 이미 만들어진 SceneGraph JSON 경로 (그대로 다시 저장)

사용:
  # SceneGraph 생성 + 요약 출력 (data/scene3d_scene_graphs/<scene>.json)
  uv run python tools/generate_scene_graph.py --source 00800

  # HM3D 소스일 때만: bbox 오버레이 스냅샷으로 정렬 검증
  uv run python tools/generate_scene_graph.py --source 00800 --overlay
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p


def parse_args():
    parser = argparse.ArgumentParser(description="3D scene → SceneGraph 생성 (Stage 1)")
    parser.add_argument(
        "--source", default="00800",
        help="HM3D scene id | mesh 파일 경로(.glb/.obj/.ply) | SceneGraph JSON 경로",
    )
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--overlay", action="store_true",
                        help="bbox 오버레이 스냅샷 생성 (HM3D 소스 전용)")
    parser.add_argument("--out-dir", default="data/scene3d_scene_graphs")
    parser.add_argument("--report-dir", default="reports/scene3d")
    parser.add_argument("--top-n", type=int, default=25, help="오버레이할 최대 객체 수")
    return parser.parse_args()


def spawn_bbox_marker(cid: int, center, size, color) -> int:
    """반투명 box 마커 (collision 없음)."""
    vis = p.createVisualShape(
        p.GEOM_BOX,
        halfExtents=(np.array(size) / 2.0).tolist(),
        rgbaColor=color,
        physicsClientId=cid,
    )
    return p.createMultiBody(
        baseMass=0,
        baseVisualShapeIndex=vis,
        basePosition=list(center),
        physicsClientId=cid,
    )


def main():
    args = parse_args()

    from scene3d.mesh_loader import convert_glb_to_obj, load_static_scene, scene_extent_pybullet
    from scene3d.sources import generate_scene_graph, resolve_source

    t0 = time.time()
    try:
        source = resolve_source(args.source, split=args.split)
    except Exception as e:
        print(f"오류: 입력 판별/해석 실패 — {e}")
        sys.exit(1)
    print(f"[0/3] 입력 판별: kind={source.kind} scene_id={source.scene_id} "
          f"({time.time()-t0:.1f}s)")

    # 시각 mesh와 동일한 월드 정렬을 위해 mesh_loader의 offset 재사용
    converted = convert_glb_to_obj(source.glb_path, source.scene_id)

    t0 = time.time()
    try:
        sg = generate_scene_graph(source, offset=converted.offset)
    except ValueError as e:
        print(f"오류: {e}")
        sys.exit(1)
    print(f"[1/3] SceneGraph 생성: 객체 {len(sg.objects)}개, "
          f"지지면 {len(sg.support_surfaces)}개 ({time.time()-t0:.1f}s)")

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{source.scene_id}.json")
    sg.save(out_path)

    cats = Counter(o.extra.get("category", "?") for o in sg.objects)
    print(f"[2/3] SceneGraph 저장: {out_path}")
    print(f"      상위 카테고리: {cats.most_common(10)}")
    print("      지지면 후보:")
    for s in sg.support_surfaces[:8]:
        area = (s.bounds["x"][1] - s.bounds["x"][0]) * (s.bounds["y"][1] - s.bounds["y"][0])
        print(f"        {s.id:28s} 높이 {s.height:.2f}m 면적 {area:.2f}m²")

    if not args.overlay:
        print("[3/3] 오버레이 생략 (--overlay로 활성화)")
        return
    if source.kind != "hm3d":
        print(f"[3/3] 오버레이는 HM3D 소스 전용입니다 (현재 kind={source.kind})")
        return

    # ── 오버레이 스냅샷 (HM3D 소스: 인스턴스 단위 상세 표시) ──────────────
    cid = p.connect(p.DIRECT)
    load_static_scene(converted, cid, collision=False)
    lo, hi = scene_extent_pybullet(converted)
    extent = hi - lo
    d_max = float(max(extent[0], extent[1]))

    support_ids = {s.id for s in sg.support_surfaces}
    green = [0.1, 0.9, 0.2, 0.55]
    blue = [0.2, 0.4, 0.95, 0.35]
    shown = 0
    for obj in sorted(sg.objects, key=lambda o: -float(np.prod(o.size))):
        is_support = obj.id in support_ids
        if not is_support and shown >= args.top_n:
            continue
        spawn_bbox_marker(cid, obj.position, obj.size, green if is_support else blue)
        shown += 1

    from PIL import Image, ImageDraw

    os.makedirs(args.report_dir, exist_ok=True)
    views = {
        "top": dict(target=[0, 0, 0], distance=d_max * 0.85, yaw=0, pitch=-89.5),
        "persp": dict(target=[0, 0, float(extent[2]) * 0.25], distance=d_max * 0.85,
                      yaw=45, pitch=-40),
    }
    w0, h0 = 1100, 820
    grid = Image.new("RGB", (w0 * 2, h0), (20, 20, 20))
    for i, (name, cam) in enumerate(views.items()):
        view = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=cam["target"], distance=cam["distance"],
            yaw=cam["yaw"], pitch=cam["pitch"], roll=0, upAxisIndex=2,
            physicsClientId=cid,
        )
        proj = p.computeProjectionMatrixFOV(
            fov=60, aspect=w0 / h0, nearVal=0.05, farVal=d_max * 3, physicsClientId=cid
        )
        _, _, rgba, _, _ = p.getCameraImage(
            w0, h0, viewMatrix=view, projectionMatrix=proj,
            renderer=p.ER_TINY_RENDERER, physicsClientId=cid,
        )
        frame = np.array(rgba, dtype=np.uint8).reshape(h0, w0, 4)[:, :, :3]
        img = Image.fromarray(frame)
        ImageDraw.Draw(img).text(
            (12, 10),
            f"{source.scene_id} — {name} (green=support, blue=object bbox)",
            fill=(255, 220, 0),
        )
        grid.paste(img, (i * w0, 0))

    out_png = os.path.join(args.report_dir, f"{source.scene_id}_semantic.png")
    grid.save(out_png)
    print(f"[3/3] 오버레이 스냅샷: {out_png}")
    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
