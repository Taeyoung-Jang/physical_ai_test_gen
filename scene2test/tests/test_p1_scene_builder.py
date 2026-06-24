"""P1 완료 기준 검증 테스트.

- Franka Panda URDF 로드
- IK 성공
- 경로 보간
- 충돌 거리 쿼리

실행: uv run python tests/test_p1_scene_builder.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import yaml

from scene_graph import SceneGraph, SupportSurface, ObjectNode, Relation, Role
from scene_builder import connect, reset_simulation, load_scene, capture_frame
from sim_runner import (
    load_robot,
    load_robot_config,
    solve_ik,
    interpolate_joint_path,
    run_kinematic_check,
)


def make_test_scene() -> SceneGraph:
    return SceneGraph(
        scene_id="test_p1",
        support_surfaces=[
            SupportSurface("table_1", "plane", 0.0,
                           {"x": [0.20, 0.80], "y": [-0.35, 0.35]})
        ],
        objects=[
            ObjectNode("red_block", Role.TARGET,    [0.45, -0.10, 0.05],
                       [0.06, 0.06, 0.08], True, "block"),
            ObjectNode("blue_obstacle", Role.OBSTACLE, [0.35, -0.08, 0.05],
                       [0.08, 0.08, 0.08], True, "block"),
            ObjectNode("tray", Role.DESTINATION,    [0.60,  0.20, 0.03],
                       [0.18, 0.12, 0.04], False, "tray"),
        ],
        meta={"source": "test"},
    )


def main():
    print("=== P1 Scene Builder + Sim Runner 검증 ===\n")

    # 1. PyBullet 연결 (DIRECT)
    os.environ["PYBULLET_MODE"] = "DIRECT"
    cid = connect()
    print(f"[1] PyBullet 연결 OK  (client_id={cid})")

    # 2. 장면 로드
    reset_simulation()
    sg = make_test_scene()
    body_map = load_scene(sg)
    print(f"[2] 장면 로드 OK  body_map={body_map}")
    assert "red_block" in body_map
    assert "tray" in body_map

    # 3. Franka Panda URDF 로드
    robot_cfg = load_robot_config("config/robot_config.yaml")
    robot_id = load_robot(robot_cfg)
    print(f"[3] Franka Panda 로드 OK  (body_id={robot_id})")
    assert robot_id >= 0

    # 4. IK 풀기
    target_pos = sg.target().position
    q_grasp = solve_ik(target_pos, None, robot_cfg)
    print(f"[4] IK {'성공' if q_grasp else '실패'}  target={target_pos}")
    assert q_grasp is not None, "IK 실패 — 로봇이 target에 도달해야 합니다"

    # 5. 경로 보간
    home_q = [0, -3.14/4, 0, -3*3.14/4, 0, 3.14/2, 3.14/4]
    path = interpolate_joint_path(home_q[:7], q_grasp, n_samples=5)
    print(f"[5] 경로 보간 OK  waypoints={len(path)}")
    assert len(path) == 5

    # 6. Kinematic oracle 전체 실행
    obstacle_ids = [body_map["blue_obstacle"]]
    result = run_kinematic_check(
        target_pos=sg.target().position,
        destination_pos=sg.destination().position,
        obstacle_body_ids=obstacle_ids,
        human_zone_body_ids=[],
        destination_body_id=body_map["tray"],
        robot_body_id=robot_id,
        robot_cfg=robot_cfg,
        occlusion_ratio=0.0,
    )
    print(f"[6] KinematicResult:")
    print(f"    ik_success            = {result.ik_success}")
    print(f"    robot_to_target_dist  = {result.robot_to_target_distance:.3f} m")
    print(f"    reach_margin          = {result.reach_margin:.3f} m")
    print(f"    path_min_obstacle_dist= {result.path_min_obstacle_dist:.3f} m")
    print(f"    target_clearance      = {result.target_clearance:.3f} m")
    print(f"    ee_path points        = {len(result.ee_path)}")
    assert result.ik_success
    assert result.reach_margin > 0

    # 7. 카메라 스냅샷
    frame = capture_frame()
    print(f"[7] 스냅샷 캡처 OK  shape={frame.shape}")
    assert frame.shape == (480, 640, 3)

    print("\n✅ P1 완료 기준 전부 통과")


if __name__ == "__main__":
    main()
