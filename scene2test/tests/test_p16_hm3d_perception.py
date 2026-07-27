"""test_p16 — HM3D RGB-D 인식 SceneGraph + GT 비교 검증 (Phase 4).

HM3D 데이터셋(tar)이 없는 환경에서는 전체를 skip한다.

실행:
  PYBULLET_MODE=DIRECT uv run --extra hm3d python tests/test_p16_hm3d_perception.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np


def test_extract_object_pointclouds_mapping():
    """V-1: valid mask 기반 픽셀↔포인트 역매핑이 정확한지 합성 데이터로 검증."""

    from vision.rgbd_to_graph import (
        CameraIntrinsics,
        depth_to_pointcloud,
        extract_object_pointclouds,
    )

    h, w = 8, 10
    depth = np.zeros((h, w), dtype=np.float32)
    # 왼쪽 절반만 유효 depth(1m), 오른쪽 절반 invalid(0)
    depth[:, : w // 2] = 1.0
    intr = CameraIntrinsics(width=w, height=h, fx=10.0, fy=10.0)
    pcd, valid = depth_to_pointcloud(depth, intr, return_valid_mask=True)
    assert int(valid.sum()) == h * (w // 2) == len(np.asarray(pcd.points))

    # 마스크: (2..3)행 (1..2)열 → 유효 영역 내 4픽셀
    mask = np.zeros((h, w), dtype=bool)
    mask[2:4, 1:3] = True
    out = extract_object_pointclouds(pcd, {"obj": mask}, (h, w), valid_mask=valid)
    pts = np.asarray(out["obj"].points)
    assert len(pts) == 4, f"매핑된 포인트 수 {len(pts)} != 4"
    # 해당 픽셀의 역투영 좌표와 정확히 일치해야 함 (버그 있던 구현은 임의 포인트 반환)
    expect = []
    for v in (2, 3):
        for u in (1, 2):
            z = 1.0
            expect.append([(u - intr.cx) * z / intr.fx, (v - intr.cy) * z / intr.fy, z])
    assert np.allclose(sorted(pts.tolist()), sorted(expect)), "픽셀↔포인트 매핑 불일치"

    # 유효 영역 밖 마스크 → 빈 결과
    mask2 = np.zeros((h, w), dtype=bool)
    mask2[:, w // 2:] = True
    out2 = extract_object_pointclouds(pcd, {"obj": mask2}, (h, w), valid_mask=valid)
    assert "obj" not in out2
    print("[1] V-1 픽셀↔포인트 매핑 OK (합성 검증)")


def test_hm3d_perception_e2e():
    from hm3d.dataset import DEFAULT_DATASET_DIR, HM3DDataset

    if not os.path.isdir(DEFAULT_DATASET_DIR):
        print(f"SKIP: HM3D 데이터셋 없음 ({DEFAULT_DATASET_DIR})")
        return

    import pybullet as p
    import pybullet_data

    from hm3d.loader import (
        convert_glb_to_obj,
        find_free_floor_spots,
        load_hm3d_static,
        scene_extent_pybullet,
    )
    from hm3d.perception import (
        capture_rgbd_seg,
        compare_with_gt,
        detect_spawned_objects,
        detect_surface_clutter,
        estimate_surface_height,
        gt_clutter_on_surface,
        view_to_world_pointcloud,
    )
    from hm3d.semantics import build_scene_graph, extract_instances
    from hm3d.workspace import setup_workspace_auto
    from sim_runner import load_robot_config

    ds = HM3DDataset(split="minival")
    extracted = ds.extract("00800")
    converted = convert_glb_to_obj(extracted.glb_path, extracted.entry.scene_dir)
    cid = p.connect(p.DIRECT)
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    scene_ids = load_hm3d_static(converted, cid, collision=True)
    lo, hi = scene_extent_pybullet(converted)
    _, floor_z = find_free_floor_spots(cid, lo, hi)
    instances = extract_instances(
        extracted.semantic_glb_path, extracted.semantic_txt_path,
        offset=converted.offset,
    )
    sg = build_scene_graph(instances, scene_id=extracted.entry.scene_dir, include_structural=True)
    robot_cfg = load_robot_config("config/robot_config.yaml")
    ws = setup_workspace_auto(converted, scene_ids, sg, floor_z, robot_cfg, cid)

    # 캡처 + 인식
    base = np.array(ws.robot_base_pos[:2])
    tgt = np.array(ws.target_pos)
    inward = (tgt[:2] - base) / (np.linalg.norm(tgt[:2] - base) + 1e-9)
    perp = np.array([-inward[1], inward[0]])
    eye_xy = tgt[:2] - inward * 0.35 + perp * 0.75
    eye = [float(eye_xy[0]), float(eye_xy[1]), ws.surface.top_z + 0.60]
    view = capture_rgbd_seg(cid, eye, [tgt[0], tgt[1], ws.surface.top_z + 0.05])
    pcd_world, valid = view_to_world_pointcloud(view)

    # 2) 좌표계 검증: 상면 높이 실측이 GT의 3cm 이내 (GL→CV 플립 확인)
    h_meas = estimate_surface_height(pcd_world, ws.surface)
    assert h_meas is not None
    assert abs(h_meas - ws.surface.top_z) < 0.03, \
        f"상면 실측 {h_meas:.3f} vs GT {ws.surface.top_z:.3f} — 좌표계 오류?"
    print(f"[2] 좌표계 OK: 상면 실측 오차 {abs(h_meas-ws.surface.top_z)*100:.1f}cm")

    # 3) spawn 객체 3종 인식 + 위치 오차 5cm 이내
    spawned = detect_spawned_objects(view, pcd_world, valid, ws.body_map)
    assert len(spawned) == 3, f"spawn 인식 {len(spawned)}/3"
    for det in spawned:
        node = ws.sg.get_object(det.det_id)
        err = float(np.linalg.norm(det.center - np.array(node.position)))
        assert err < 0.05, f"{det.det_id} 위치오차 {err*100:.1f}cm"
    print("[3] spawn 인식 OK: 3/3, 위치오차 < 5cm")

    # 4) 클러터 + 리포트 구조
    exclude = list(ws.body_map.values()) + [ws.robot_body_id, ws.pedestal_body_id]
    clutter = detect_surface_clutter(pcd_world, valid, view.seg, ws.surface, exclude)
    gt_c = gt_clutter_on_surface(instances, ws.surface)
    report = compare_with_gt(ws, spawned + clutter, h_meas, gt_c)
    assert set(report.spawned_errors.keys()) == {"target_block", "obstacle_block", "tray"}
    assert all(e["detected"] for e in report.spawned_errors.values())
    d = report.to_dict()
    assert "clutter_matched" in d and "surface_height_error_m" in d
    print(f"[4] 리포트 OK: 클러터 매칭 {len(report.clutter_matched)} / "
          f"누락 {len(report.clutter_missed)} / 허위 {len(report.clutter_spurious)}")

    p.disconnect(physicsClientId=cid)


def main():
    test_extract_object_pointclouds_mapping()
    test_hm3d_perception_e2e()
    print("\ntest_p16 PASS")


if __name__ == "__main__":
    main()
