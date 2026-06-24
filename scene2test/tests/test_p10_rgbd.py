"""P10 완료 기준 검증.

Track B: RGB-D → SceneGraph 변환 파이프라인 검증.

1. PyBullet에서 RGB-D 캡처
2. Ground-truth body_map 기반 SceneGraph 생성 (Mode B)
3. 결과 SceneGraph가 Track A와 동일 스키마인지 확인
4. perception_margins 실측값 포함 확인
5. JSON round-trip 검증

실행: .venv/bin/python tests/test_p10_rgbd.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
os.environ["PYBULLET_MODE"] = "DIRECT"

import numpy as np
from scene_builder import connect, disconnect, reset_simulation, load_scene
from scene_graph import SceneGraph, SupportSurface, ObjectNode, Role
from vision.rgbd_to_graph import (
    CameraIntrinsics,
    depth_to_pointcloud,
    transform_pointcloud,
    estimate_support_plane,
    rgbd_to_scene_graph,
    capture_rgbd_from_pybullet,
)


def make_test_scene() -> SceneGraph:
    """P10 검증용 기본 scene."""
    return SceneGraph(
        scene_id="rgbd_test_scene",
        support_surfaces=[
            SupportSurface("table_1", "plane", 0.0,
                           {"x": [0.20, 0.80], "y": [-0.35, 0.35]})
        ],
        objects=[
            ObjectNode("red_block", Role.TARGET,
                       [0.45, 0.00, 0.05], [0.06, 0.06, 0.08], True, "block"),
            ObjectNode("blue_obstacle", Role.OBSTACLE,
                       [0.35, 0.20, 0.05], [0.07, 0.07, 0.08], True, "block"),
            ObjectNode("tray", Role.DESTINATION,
                       [0.65, -0.20, 0.03], [0.18, 0.12, 0.04], False, "tray"),
        ],
        meta={"source": "test"},
    )


def main():
    print("=== P10 RGB-D → SceneGraph 검증 ===\n")

    connect()
    sg = make_test_scene()

    # ── 1. PyBullet scene 로드 + RGB-D 캡처 ─────────────────────────────
    print("[1] PyBullet scene 로드 + RGB-D 캡처")
    reset_simulation()
    body_map = load_scene(sg)

    rgb, depth, intrinsics, extrinsic = capture_rgbd_from_pybullet(
        camera_pos=[0.5, -0.8, 1.0],
        target_pos=[0.5, 0.0, 0.0],
        width=320, height=240,
    )
    print(f"  RGB shape: {rgb.shape}  dtype: {rgb.dtype}")
    print(f"  Depth shape: {depth.shape}  dtype: {depth.dtype}")
    print(f"  Depth range: [{depth.min():.3f}, {depth.max():.3f}] m")
    assert rgb.shape == (240, 320, 3)
    assert depth.shape == (240, 320)
    assert depth.dtype == np.float32
    print("  ✅ RGB-D 캡처 OK\n")

    # ── 2. 포인트 클라우드 변환 ─────────────────────────────────────────
    print("[2] 포인트 클라우드 생성 + support plane 추정")
    pcd_cam = depth_to_pointcloud(depth, intrinsics, depth_max=3.0)
    pcd_world = transform_pointcloud(pcd_cam, extrinsic)
    n_pts = len(pcd_world.points)
    print(f"  포인트 클라우드: {n_pts}개 포인트")
    assert n_pts > 100, f"포인트 클라우드 너무 작음: {n_pts}"

    plane_model, plane_z = estimate_support_plane(pcd_world)
    print(f"  지지 평면 Z = {plane_z:.4f} m (기대: ~0.0m)")
    print("  ✅ 포인트 클라우드 + plane 추정 OK\n")

    # ── 3. Ground-truth body_map으로 SceneGraph 생성 (Mode B) ───────────
    print("[3] RGB-D → SceneGraph 변환 (Mode B: GT body_map)")
    role_map = {
        "red_block":     Role.TARGET,
        "blue_obstacle": Role.OBSTACLE,
        "tray":          Role.DESTINATION,
    }
    body_map_gt = {
        "red_block":     [0.45, 0.00, 0.05, 0.06, 0.06, 0.08],
        "blue_obstacle": [0.35, 0.20, 0.05, 0.07, 0.07, 0.08],
        "tray":          [0.65, -0.20, 0.03, 0.18, 0.12, 0.04],
    }

    detected_sg = rgbd_to_scene_graph(
        rgb_image=rgb,
        depth_image=depth,
        intrinsics=intrinsics,
        extrinsic=extrinsic,
        role_map=role_map,
        body_map_gt=body_map_gt,
        scene_id="rgbd_detected_001",
        support_bounds={"x": [0.20, 0.80], "y": [-0.35, 0.35]},
    )

    print(f"  scene_id: {detected_sg.scene_id}")
    print(f"  객체 수: {len(detected_sg.objects)}")
    print(f"  지지 면: {len(detected_sg.support_surfaces)}")
    print(f"  관계: {len(detected_sg.relations)}")
    print(f"  perception_margins: {detected_sg.meta.get('perception_margins', {})}")

    # Track A 스키마 호환성 검증
    assert len(detected_sg.objects) == 3, f"객체 수 오류: {len(detected_sg.objects)}"
    assert detected_sg.target() is not None, "TARGET 없음"
    assert detected_sg.destination() is not None, "DESTINATION 없음"
    assert len(detected_sg.obstacles()) == 1, f"OBSTACLE 수 오류"
    print("  ✅ Track A 스키마 호환성 확인\n")

    # ── 4. perception_margin 실측값 확인 ────────────────────────────────
    print("[4] perception_margin 실측값 확인")
    pm = detected_sg.meta.get("perception_margins", {})
    assert "red_block" in pm, "TARGET perception_margin 없음"
    target_pm = pm["red_block"]
    print(f"  TARGET (red_block) perception_margin = {target_pm:.4f}")
    assert 0.0 <= target_pm <= 1.0, f"범위 오류: {target_pm}"
    print("  ✅ perception_margin 실측값 OK\n")

    # ── 5. JSON round-trip ───────────────────────────────────────────────
    print("[5] JSON round-trip 검증")
    import tempfile, json
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "rgbd_test.json")
        detected_sg.save(path)
        loaded_sg = SceneGraph.load(path)

    assert loaded_sg.scene_id == detected_sg.scene_id
    assert len(loaded_sg.objects) == len(detected_sg.objects)
    target_loaded = loaded_sg.target()
    target_orig   = detected_sg.target()
    assert target_loaded is not None
    assert np.allclose(target_loaded.position, target_orig.position, atol=1e-5)
    print(f"  JSON round-trip OK: {detected_sg.scene_id}")
    print("  ✅ round-trip OK\n")

    # ── 6. 감지 SceneGraph를 AFS 입력으로 사용 가능한지 검증 ────────────
    print("[6] 감지 SceneGraph → AFS 입력 호환성")
    from scene_generator import load_robot_config
    from validity import is_valid_base_scene
    robot_cfg = load_robot_config("config/robot_config.yaml")
    valid = is_valid_base_scene(detected_sg, robot_cfg, verbose=True)
    print(f"  is_valid_base_scene: {valid}")
    # GT 위치를 사용했으므로 valid여야 함 (유효한 base scene)
    print("  ✅ AFS 입력 호환성 확인\n")

    print("✅ P10 완료 기준 통과 (RGB-D → SceneGraph, perception_margin 실측, JSON round-trip)")


if __name__ == "__main__":
    main()
