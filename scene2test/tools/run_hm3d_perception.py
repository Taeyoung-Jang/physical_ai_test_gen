"""run_hm3d_perception.py — HM3D 씬에서 RGB-D 인식 SceneGraph 생성 + GT 비교.

흐름: 씬 로드 + 작업공간 구성 (Phase 3 재사용)
      → RGB-D + segmentation 캡처
      → point cloud → spawn 객체(seg mask) + 클러터(DBSCAN) 인식
      → 인식 SceneGraph 저장 + semantic GT 대비 오차 리포트 + 오버레이 PNG

사용:
  PYBULLET_MODE=DIRECT uv run python tools/run_hm3d_perception.py --scene 00800

출력:
  data/hm3d_scene_graphs/<scene>_rgbd.json   인식 SceneGraph
  reports/hm3d/<scene>_perception.json       비교 지표
  reports/hm3d/<scene>_perception.png        RGB + bbox 오버레이
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p


def parse_args():
    parser = argparse.ArgumentParser(description="HM3D RGB-D 인식 + GT 비교")
    parser.add_argument("--scene", default="00800", help="씬 참조 (semantic 보유 씬)")
    parser.add_argument("--split", default="minival", choices=["minival", "val", "train"])
    parser.add_argument("--surface", type=int, default=-1, help="지지면 인덱스 (-1=자동)")
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=600)
    parser.add_argument("--out-dir", default="data/hm3d_scene_graphs")
    parser.add_argument("--report-dir", default="reports/hm3d")
    return parser.parse_args()


def perception_camera(ws) -> tuple[list[float], list[float]]:
    """작업 패치를 비스듬히 내려다보는 카메라 (side 45°)."""
    base = np.array(ws.robot_base_pos[:2])
    target = np.array(ws.target_pos)
    inward = target[:2] - base
    inward = inward / (np.linalg.norm(inward) + 1e-9)
    perp = np.array([-inward[1], inward[0]])
    top = ws.surface.top_z
    eye_xy = target[:2] - inward * 0.35 + perp * 0.75
    eye = [float(eye_xy[0]), float(eye_xy[1]), top + 0.60]
    cam_target = [float(target[0]), float(target[1]), top + 0.05]
    return eye, cam_target


def main():
    args = parse_args()

    from hm3d.dataset import HM3DDataset
    from hm3d.loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_hm3d_static,
        scene_extent_pybullet,
    )
    from hm3d.perception import (
        build_perceived_scene_graph,
        capture_rgbd_seg,
        compare_with_gt,
        detect_spawned_objects,
        detect_surface_clutter,
        estimate_surface_height,
        gt_clutter_on_surface,
        project_bbox_to_image,
        view_to_world_pointcloud,
    )
    from hm3d.semantics import build_scene_graph, extract_instances
    from hm3d.workspace import WorkspacePlacementError, setup_workspace
    from sim_runner import load_robot_config

    # ── 씬 + 작업공간 (Phase 3 재사용) ──────────────────────────────────
    t0 = time.time()
    ds = HM3DDataset(split=args.split)
    extracted = ds.extract(args.scene)
    entry = extracted.entry
    if extracted.semantic_glb_path is None:
        print(f"오류: {entry.scene_dir}에는 semantic annotation이 없습니다.")
        sys.exit(1)

    converted = convert_glb_to_obj(extracted.glb_path, entry.scene_dir)
    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_hm3d_static(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)
    instances = extract_instances(
        extracted.semantic_glb_path, extracted.semantic_txt_path,
        offset=converted.offset,
    )
    sg = build_scene_graph(instances, scene_id=entry.scene_dir, include_structural=True)
    robot_cfg = load_robot_config("config/robot_config.yaml")

    candidates = (
        sg.support_surfaces if args.surface < 0 else [sg.support_surfaces[args.surface]]
    )
    ws = None
    for surf in candidates:
        try:
            ws = setup_workspace(
                converted, scene_ids, sg, surf.id, floor_z, robot_cfg, cid
            )
            break
        except WorkspacePlacementError:
            continue
    if ws is None:
        print("오류: 로봇 배치 실패")
        sys.exit(1)
    print(f"[1/4] 작업공간: {entry.scene_dir} {ws.surface.id} "
          f"({time.time()-t0:.1f}s)")

    # ── 캡처 + 인식 ─────────────────────────────────────────────────────
    t0 = time.time()
    eye, cam_target = perception_camera(ws)
    view = capture_rgbd_seg(
        cid, eye, cam_target, width=args.width, height=args.height
    )
    pcd_world, valid = view_to_world_pointcloud(view)
    n_pts = len(np.asarray(pcd_world.points))

    spawned = detect_spawned_objects(view, pcd_world, valid, ws.body_map)
    exclude = list(ws.body_map.values()) + [ws.robot_body_id, ws.pedestal_body_id]
    clutter = detect_surface_clutter(
        pcd_world, valid, view.seg, ws.surface, exclude
    )
    height_measured = estimate_surface_height(pcd_world, ws.surface)
    print(f"[2/4] 인식 ({time.time()-t0:.1f}s): 포인트 {n_pts:,}개, "
          f"spawn 객체 {len(spawned)}/3, 클러터 클러스터 {len(clutter)}개")
    if height_measured is not None:
        print(f"      상면 높이 실측 {height_measured:.3f}m "
              f"(GT {ws.surface.top_z:.3f}m)")

    # ── 인식 SceneGraph 저장 ────────────────────────────────────────────
    role_map = {o.id: o.role for o in ws.sg.objects}
    perceived_sg = build_perceived_scene_graph(
        scene_id=f"hm3d_{entry.scene_dir}_rgbd",
        surface=ws.surface,
        surface_height_measured=height_measured,
        detections=spawned + clutter,
        role_map=role_map,
    )
    os.makedirs(args.out_dir, exist_ok=True)
    sg_path = os.path.join(args.out_dir, f"{entry.scene_dir}_rgbd.json")
    perceived_sg.save(sg_path)

    # ── GT 비교 ─────────────────────────────────────────────────────────
    gt_clutter = gt_clutter_on_surface(instances, ws.surface)
    report = compare_with_gt(ws, spawned + clutter, height_measured, gt_clutter)
    os.makedirs(args.report_dir, exist_ok=True)
    report_path = os.path.join(
        args.report_dir, f"{entry.scene_dir}_perception.json"
    )
    with open(report_path, "w") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)

    print(f"[3/4] GT 비교 → {report_path}")
    for oid, err in report.spawned_errors.items():
        if err.get("detected"):
            print(f"        {oid:16s} 위치오차 {err['position_error_m']*100:.1f}cm "
                  f"크기오차 {err['size_error_max_m']*100:.1f}cm "
                  f"({err['n_points']}pts)")
        else:
            print(f"        {oid:16s} 미검출")
    if report.surface_height_error_m is not None:
        print(f"        상면 높이 오차 {report.surface_height_error_m*100:.1f}cm")
    print(f"        클러터: 매칭 {len(report.clutter_matched)} / "
          f"누락 {len(report.clutter_missed)} / 허위 {len(report.clutter_spurious)}")
    for m in report.clutter_matched:
        print(f"          ✓ {m['gt']} ← {m['det']} "
              f"(중심오차 {m['center_error_m']*100:.1f}cm)")
    for m in report.clutter_missed:
        print(f"          ✗ 누락: {m['gt']}")

    # ── 오버레이 PNG ────────────────────────────────────────────────────
    from PIL import Image, ImageDraw

    img = Image.fromarray(view.rgb.copy())
    draw = ImageDraw.Draw(img)
    # GT: spawn(초록) + 클러터(노랑) / 인식: 빨강 점선 대신 실선 얇게
    for node in ws.sg.objects:
        if node.extra.get("hm3d_context"):
            continue
        bb = project_bbox_to_image(
            np.array(node.position), np.array(node.size), view
        )
        if bb:
            draw.rectangle(bb, outline=(0, 220, 60), width=3)
            draw.text((bb[0], max(0, bb[1] - 14)), f"GT {node.id}", fill=(0, 220, 60))
    for inst in gt_clutter:
        bb = project_bbox_to_image(inst.center, inst.size, view)
        if bb:
            draw.rectangle(bb, outline=(250, 210, 0), width=2)
            draw.text((bb[0], max(0, bb[1] - 14)),
                      f"GT {inst.category}", fill=(250, 210, 0))
    for det in spawned + clutter:
        bb = project_bbox_to_image(det.center, det.size, view)
        if bb:
            draw.rectangle(bb, outline=(255, 40, 40), width=1)
            draw.text((bb[0] + 2, bb[3] + 2), det.det_id, fill=(255, 40, 40))

    png_path = os.path.join(args.report_dir, f"{entry.scene_dir}_perception.png")
    img.save(png_path)
    print(f"[4/4] 오버레이: {png_path}")

    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
