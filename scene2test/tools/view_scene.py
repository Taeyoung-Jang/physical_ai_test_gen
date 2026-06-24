"""tools/view_scene.py — 씬 + 로봇 3D 시각화 도구.

두 가지 모드:
  --gui      : PyBullet GUI 창 열기 (인터랙티브, 마우스로 회전/줌)
  --snapshot : TinyRenderer로 PNG 저장 (헤드리스)

실행 예:
  # 인터랙티브 3D 뷰어 (로봇 경로 애니메이션 포함)
  uv run python tools/view_scene.py --scene data/scene_library/scene_00100.json --gui

  # PNG 스냅샷 저장
  uv run python tools/view_scene.py --scene data/scene_library/scene_00100.json --snapshot
"""
from __future__ import annotations

import argparse
import math
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
import pybullet as p


def parse_args():
    parser = argparse.ArgumentParser(description="씬 + 로봇 3D 뷰어")
    parser.add_argument(
        "--scene",
        default="data/scene_library/scene_00100.json",
        help="SceneGraph JSON 경로",
    )
    parser.add_argument("--gui", action="store_true", help="PyBullet GUI 창 열기")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="PNG 스냅샷을 reports/ 에 저장",
    )
    parser.add_argument(
        "--animate",
        action="store_true",
        help="--gui 모드에서 로봇 경로 애니메이션 실행",
    )
    parser.add_argument(
        "--output",
        default="reports/scene_snapshot.png",
        help="스냅샷 저장 경로",
    )
    return parser.parse_args()


def setup_pybullet(gui: bool) -> int:
    mode = p.GUI if gui else p.DIRECT
    cid = p.connect(mode)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    if gui:
        p.resetDebugVisualizerCamera(
            cameraDistance=1.4,
            cameraYaw=50,
            cameraPitch=-30,
            cameraTargetPosition=[0.45, 0.0, 0.1],
            physicsClientId=cid,
        )
        # 불필요한 GUI 패널 숨김
        p.configureDebugVisualizer(p.COV_ENABLE_GUI, 0, physicsClientId=cid)
        p.configureDebugVisualizer(p.COV_ENABLE_SHADOWS, 1, physicsClientId=cid)
    return cid


def load_scene_and_robot(scene_path: str, cid: int):
    from scene_builder import load_scene, reset_simulation
    from scene_graph import SceneGraph
    from sim_runner import load_robot, load_robot_config

    # 환경 변수 없이 직접 cid 사용하도록 패치
    import scene_builder
    scene_builder._client_id = cid

    import sim_runner
    sim_runner._ROBOT_BODY_ID = None

    reset_simulation()
    sg = SceneGraph.load(scene_path)
    body_map = load_scene(sg)

    robot_cfg = load_robot_config("config/robot_config.yaml")
    robot_id = load_robot(robot_cfg)

    return sg, body_map, robot_id, robot_cfg


def print_scene_info(sg, body_map: dict):
    print("\n=== 씬 정보 ===")
    print(f"  scene_id : {sg.scene_id}")
    print(f"  객체 수  : {len(sg.objects)}")
    print()

    role_label = {
        "target":      "TARGET      (빨강)",
        "obstacle":    "OBSTACLE    (파랑)",
        "destination": "DESTINATION (초록)",
        "human_zone":  "HUMAN_ZONE  (주황)",
        "distractor":  "DISTRACTOR  (회색)",
    }
    for obj in sg.objects:
        label = role_label.get(obj.role, obj.role)
        pos = [f"{v:.3f}" for v in obj.position]
        size = [f"{v:.3f}" for v in obj.size]
        print(f"  [{label}]")
        print(f"    id      : {obj.id}")
        print(f"    position: ({', '.join(pos)}) m")
        print(f"    size    : ({', '.join(size)}) m")

    print()
    print("=== 로봇 구조 (Franka Panda) ===")
    print("  DOF      : 7 (arm) + 2 (finger)")
    print("  최대 도달 : 0.855 m")
    print("  EE link  : index 11 (panda_hand)")
    print("  홈 자세  : [0, -45°, 0, -135°, 0, 90°, 45°]")
    print()
    print("=== 동작 순서 (Kinematic Oracle) ===")
    print("  1. Home 자세")
    print("  2. Pre-grasp  (target 위 +10cm)")
    print("  3. Grasp      (target 위치)")
    print("  ※ 각 구간: joint-space 선형 보간 × 12 waypoints")
    print("  ※ 물리 시뮬레이션 없이 IK + 거리 쿼리만 실행")


def animate_kinematic_path(sg, robot_cfg: dict, cid: int):
    from sim_runner import solve_ik, interpolate_joint_path, set_joint_state, get_robot_id

    target = sg.target()
    if target is None:
        print("  (TARGET 객체 없음 — 애니메이션 스킵)")
        return

    target_pos = list(target.position)
    pre_grasp_pos = [target_pos[0], target_pos[1], target_pos[2] + 0.12]
    grasp_orn = p.getQuaternionFromEuler([0, math.pi, 0])

    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]

    print("\n[애니메이션] IK 계산 중...")
    q_pre = solve_ik(pre_grasp_pos, list(grasp_orn), robot_cfg)
    q_grasp = solve_ik(target_pos, list(grasp_orn), robot_cfg)

    if q_grasp is None:
        print("  IK 실패 (target 도달 불가)")
        return

    print("  IK 성공 — 경로 재생 시작 (Home → Pre-grasp → Grasp → Home)")
    print("  GUI 창에서 마우스로 회전/줌 가능\n")

    segments = [
        ("Home → Pre-grasp", home_q, q_pre or home_q),
        ("Pre-grasp → Grasp", q_pre or home_q, q_grasp),
        ("Grasp → Home", q_grasp, home_q),
    ]

    n_samples = 30
    for name, q_start, q_end in segments:
        print(f"  {name}")
        waypoints = interpolate_joint_path(q_start, q_end, n_samples)
        for q in waypoints:
            set_joint_state(q, robot_cfg)
            p.stepSimulation(physicsClientId=cid)
            time.sleep(1 / 60)


def take_snapshot(output_path: str, cid: int):
    width, height = 960, 720
    cam_target = [0.45, 0.0, 0.05]

    views = [
        ("front",      45,  -25),
        ("top",         0,  -89),
        ("side",       90,  -20),
        ("perspective", 30,  -40),
    ]

    import PIL.Image
    import PIL.ImageDraw
    import PIL.ImageFont

    frames = []
    for label, yaw, pitch in views:
        view_mat = p.computeViewMatrixFromYawPitchRoll(
            cameraTargetPosition=cam_target,
            distance=1.3,
            yaw=yaw,
            pitch=pitch,
            roll=0,
            upAxisIndex=2,
            physicsClientId=cid,
        )
        proj_mat = p.computeProjectionMatrixFOV(
            fov=60, aspect=width / height,
            nearVal=0.01, farVal=10.0,
            physicsClientId=cid,
        )
        _, _, rgba, _, _ = p.getCameraImage(
            width // 2, height // 2,
            viewMatrix=view_mat,
            projectionMatrix=proj_mat,
            renderer=p.ER_TINY_RENDERER,
            physicsClientId=cid,
        )
        arr = np.array(rgba, dtype=np.uint8).reshape(height // 2, width // 2, 4)
        img = PIL.Image.fromarray(arr[:, :, :3])
        draw = PIL.ImageDraw.Draw(img)
        draw.text((8, 8), label, fill=(255, 255, 255))
        frames.append(img)

    # 2×2 그리드로 합치기
    grid = PIL.Image.new("RGB", (width, height))
    grid.paste(frames[0], (0, 0))
    grid.paste(frames[1], (width // 2, 0))
    grid.paste(frames[2], (0, height // 2))
    grid.paste(frames[3], (width // 2, height // 2))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    grid.save(output_path)
    print(f"\n스냅샷 저장: {output_path}")
    print(f"  front / top / side / perspective 4개 뷰 포함")


def main():
    args = parse_args()

    if not args.gui and not args.snapshot:
        print("--gui 또는 --snapshot 중 하나를 선택하세요.")
        print("  예) uv run python tools/view_scene.py --gui")
        print("  예) uv run python tools/view_scene.py --snapshot")
        sys.exit(1)

    cid = setup_pybullet(gui=args.gui)

    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    sg, body_map, robot_id, robot_cfg = load_scene_and_robot(args.scene, cid)

    print_scene_info(sg, body_map)

    if args.snapshot:
        take_snapshot(args.output, cid)

    if args.gui:
        if args.animate:
            animate_kinematic_path(sg, robot_cfg, cid)

        print("\nGUI 창이 열려 있습니다.")
        print("  마우스 왼쪽 드래그 : 회전")
        print("  마우스 휠          : 줌")
        print("  마우스 오른쪽 드래그: 이동")
        print("  Ctrl+C             : 종료\n")
        try:
            while True:
                p.stepSimulation(physicsClientId=cid)
                time.sleep(1 / 60)
        except KeyboardInterrupt:
            pass

    p.disconnect(physicsClientId=cid)


if __name__ == "__main__":
    main()
