"""hm3d_scene_graph.py — HM3D semantic annotation에서 실측 SceneGraph를 생성한다.

사용:
  # SceneGraph 생성 + 요약 출력 (data/hm3d_scene_graphs/<scene>.json)
  uv run python tools/hm3d_scene_graph.py --scene 00800

  # bbox 오버레이 스냅샷으로 정렬 검증 (reports/hm3d/<scene>_semantic.png)
  uv run python tools/hm3d_scene_graph.py --scene 00800 --overlay
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p


def parse_args():
    parser = argparse.ArgumentParser(description="HM3D semantic → SceneGraph")
    parser.add_argument("--scene", default="00800", help="씬 참조 (semantic 보유 씬만 가능)")
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--dataset-dir", default=None)
    parser.add_argument("--overlay", action="store_true", help="bbox 오버레이 스냅샷 생성")
    parser.add_argument("--out-dir", default="data/hm3d_scene_graphs")
    parser.add_argument("--report-dir", default="reports/hm3d")
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

    from hm3d.dataset import HM3DDataset
    from hm3d.loader import convert_glb_to_obj, load_hm3d_static, scene_extent_pybullet
    from hm3d.semantics import build_scene_graph, extract_instances, select_support_surfaces

    ds = HM3DDataset(split=args.split, **(
        {"dataset_dir": args.dataset_dir} if args.dataset_dir else {}
    ))
    extracted = ds.extract(args.scene)
    entry = extracted.entry
    if extracted.semantic_glb_path is None:
        print(f"오류: {entry.scene_dir}에는 semantic annotation이 없습니다.")
        print("      --list로 [semantic O] 씬을 확인하세요.")
        sys.exit(1)

    # 시각 씬과 동일한 월드 정렬을 위해 loader의 offset 재사용
    converted = convert_glb_to_obj(extracted.glb_path, entry.scene_dir)

    t0 = time.time()
    instances = extract_instances(
        extracted.semantic_glb_path,
        extracted.semantic_txt_path,
        offset=converted.offset,
    )
    print(f"[1/3] 인스턴스 추출: {len(instances)}개 ({time.time()-t0:.1f}s)")

    sg = build_scene_graph(instances, scene_id=f"hm3d_{entry.scene_dir}")
    supports = select_support_surfaces(instances)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{entry.scene_dir}.json")
    sg.save(out_path)

    # 요약
    from collections import Counter
    cats = Counter(o.extra["category"] for o in sg.objects)
    n_structural = sum(sg.meta["structural_counts"].values())
    print(f"[2/3] SceneGraph 저장: {out_path}")
    print(f"      객체 {len(sg.objects)}개 / 구조물 제외 {n_structural}개")
    print(f"      상위 카테고리: {cats.most_common(10)}")
    print(f"      지지면 후보 {len(supports)}개:")
    for s in supports[:8]:
        print(f"        #{s.instance_id:4d} {s.category:20s} 높이 {s.top_z:.2f}m "
              f"면적 {s.footprint_area:.2f}m² 중심 {np.round(s.center[:2], 2).tolist()}")

    if not args.overlay:
        print("[3/3] 오버레이 생략 (--overlay로 활성화)")
        return

    # ── 오버레이 스냅샷 ─────────────────────────────────────────────────
    cid = p.connect(p.DIRECT)
    load_hm3d_static(converted, cid, collision=False)
    lo, hi = scene_extent_pybullet(converted)
    extent = hi - lo
    d_max = float(max(extent[0], extent[1]))

    # 지지면 = 초록, 그 외 객체 = 파랑 (큰 것부터 top-n)
    support_ids = {s.instance_id for s in supports}
    green = [0.1, 0.9, 0.2, 0.55]
    blue = [0.2, 0.4, 0.95, 0.35]
    shown = 0
    inst_by_id = {i.instance_id: i for i in instances}
    for obj in sorted(sg.objects, key=lambda o: -float(np.prod(o.size))):
        inst = inst_by_id[obj.extra["hm3d_instance_id"]]
        is_support = inst.instance_id in support_ids
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
            f"{entry.scene_dir} — {name} (green=support, blue=object bbox)",
            fill=(255, 220, 0),
        )
        grid.paste(img, (i * w0, 0))

    out_png = os.path.join(args.report_dir, f"{entry.scene_dir}_semantic.png")
    grid.save(out_png)
    print(f"[3/3] 오버레이 스냅샷: {out_png}")
    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
