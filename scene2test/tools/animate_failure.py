"""tools/animate_failure.py — 로봇 pick-and-place 애니메이션 GIF 생성.

전체 동작 시퀀스를 실제로 재생한다:
  Home → Pre-grasp → Grasp(그리퍼 닫기) → Lift → Pre-place → Place(그리퍼 열기) → Home

macOS에서 깨지는 ER_BULLET_HARDWARE_OPENGL 대신 ER_TINY_RENDERER로 캡처한다.

사용 예:
  # 실패 케이스 (mutation 적용)
  uv run python tools/animate_failure.py \
    --log data/search_logs/search_da0aad10.json --test-index 0

  # 성공 케이스 (원본 씬, mutation 없음)
  uv run python tools/animate_failure.py --pass-scene scene_00001

  # 모든 FAIL 케이스
  uv run python tools/animate_failure.py \
    --log data/search_logs/search_da0aad10.json --verdict FAIL --max 8
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import imageio
import numpy as np
import pybullet as p

import scene_builder
import sim_runner
from scene_builder import apply_mutation, load_scene, reset_simulation
from scene_graph import SceneGraph
from sim_runner import (
    load_robot,
    load_robot_config,
    solve_ik,
    interpolate_joint_path,
    set_joint_state,
    get_robot_id,
)


def parse_args():
    parser = argparse.ArgumentParser(description="로봇 pick-and-place 애니메이션")
    parser.add_argument("--log", help="Search 로그 파일 경로")
    parser.add_argument("--test-index", type=int, help="특정 테스트 인덱스 (0-based)")
    parser.add_argument("--verdict", choices=["FAIL", "WARN", "BLOCKED", "PASS"])
    parser.add_argument("--max", type=int, default=1, help="최대 생성 개수")
    parser.add_argument(
        "--pass-scene",
        help="성공 케이스: mutation 없이 이 씬을 애니메이션 (예: scene_00001)",
    )
    parser.add_argument("--output-dir", default="data/failure_anim")
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--samples", type=int, default=14, help="구간당 waypoint 수")
    parser.add_argument("--fps", type=int, default=20)
    parser.add_argument(
        "--physics",
        action="store_true",
        help="물리 동역학 모드: 모터 제어 + 충돌 응답 (teleport 대신 실제 시뮬레이션)",
    )
    return parser.parse_args()


def load_test_cases(log_path, test_index=None, verdict=None):
    with open(log_path, "r") as f:
        log_data = json.load(f)
    records = log_data["records"]
    scene_id = log_data["scene_id"]
    if test_index is not None:
        return [records[test_index]], scene_id
    if verdict is not None:
        return [r for r in records if r["verdict"] == verdict], scene_id
    for r in records:
        if r["verdict"] in ("FAIL", "BLOCKED"):
            return [r], scene_id
    return [], scene_id


def set_gripper(width, robot_cfg, cid):
    """그리퍼 손가락 개폐. width=0.04 완전열림, 0.0 닫힘."""
    robot_id = get_robot_id()
    for idx in robot_cfg["robot"]["finger_joint_indices"]:
        p.resetJointState(robot_id, idx, width, physicsClientId=cid)


def capture_frame(cid, width, height, yaw):
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=[0.55, -0.05, 0.1],
        distance=1.5, yaw=yaw, pitch=-35, roll=0, upAxisIndex=2,
        physicsClientId=cid,
    )
    proj = p.computeProjectionMatrixFOV(
        fov=60, aspect=width / height, nearVal=0.01, farVal=10.0,
        physicsClientId=cid,
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width, height, viewMatrix=view, projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER, physicsClientId=cid,
    )
    arr = np.array(rgba, dtype=np.uint8).reshape(height, width, 4)
    return arr[:, :, :3].copy()


OPEN, CLOSED = 0.04, 0.005


def _load_and_pose(scene_path, mutation_params, cid, robot_cfg):
    """씬+로봇 로드 후 pick-and-place pose 목록을 계산한다.

    반환: (mutated_sg, body_map, home_q, goals, err)
      goals: [(q, gripper_width), ...] — home에서 시작해 순서대로 방문할 목표
    """
    reset_simulation()
    sg = SceneGraph.load(scene_path)
    mutated_sg = apply_mutation(sg, mutation_params) if mutation_params else sg
    body_map = load_scene(mutated_sg)
    load_robot(robot_cfg)

    target = mutated_sg.target()
    dest = mutated_sg.destination()
    if target is None:
        return None, None, None, None, "target 없음"

    lift_h = robot_cfg["motion"]["lift_height"]
    pre_off = robot_cfg["motion"]["pre_offset"]
    down = list(p.getQuaternionFromEuler([0, math.pi, 0], physicsClientId=cid))
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]

    tp = list(target.position)
    grasp_q = solve_ik(tp, down, robot_cfg)
    pre_q = solve_ik([tp[0], tp[1], tp[2] + pre_off], down, robot_cfg) or home_q
    lift_q = solve_ik([tp[0], tp[1], tp[2] + lift_h], down, robot_cfg) or grasp_q
    if grasp_q is None:
        return None, None, None, None, "IK 실패 (target 도달 불가)"

    goals = [
        (pre_q,   OPEN),    # 접근
        (grasp_q, OPEN),    # 하강
        (grasp_q, CLOSED),  # 잡기
        (lift_q,  CLOSED),  # 들어올림
    ]
    if dest is not None:
        dp = list(dest.position)
        preplace_q = solve_ik([dp[0], dp[1], dp[2] + pre_off + lift_h], down, robot_cfg)
        place_q = solve_ik([dp[0], dp[1], dp[2] + pre_off], down, robot_cfg)
        if preplace_q and place_q:
            goals += [(preplace_q, CLOSED), (place_q, CLOSED),
                      (place_q, OPEN), (home_q, OPEN)]
        else:
            goals += [(home_q, CLOSED)]
    else:
        goals += [(home_q, CLOSED)]

    # IK 계산이 로봇을 마지막 pose로 옮겨놨으니 home으로 되돌림
    set_joint_state(home_q, robot_cfg)
    return mutated_sg, body_map, home_q, goals, None


def build_animation(scene_path, mutation_params, cid, robot_cfg,
                    width, height, samples):
    """[KINEMATIC] teleport로 pose 사이를 보간하며 재생. 잡은 블록은 표시용으로 붙임."""
    mutated_sg, body_map, home_q, goals, err = _load_and_pose(
        scene_path, mutation_params, cid, robot_cfg)
    if err:
        return None, err

    target_body = body_map.get(mutated_sg.target().id)
    ee_link = robot_cfg["robot"]["ee_link_index"]
    robot_id = get_robot_id()
    grasp_z_off = 0.045

    frames = []
    total = len(goals) * samples
    step = 0
    prev_q = home_q
    for q_goal, grip in goals:
        carrying = grip == CLOSED
        for q in interpolate_joint_path(prev_q, q_goal, samples):
            set_joint_state(q, robot_cfg)
            set_gripper(grip, robot_cfg, cid)
            p.stepSimulation(physicsClientId=cid)
            if carrying and target_body is not None:
                ee = p.getLinkState(robot_id, ee_link, physicsClientId=cid)[4]
                p.resetBasePositionAndOrientation(
                    target_body, [ee[0], ee[1], ee[2] - grasp_z_off],
                    [0, 0, 0, 1], physicsClientId=cid)
            yaw = 35 + 40 * (step / max(total - 1, 1))
            frames.append(capture_frame(cid, width, height, yaw))
            step += 1
        prev_q = q_goal
    return frames, None


def build_animation_physics(scene_path, mutation_params, cid, robot_cfg,
                            width, height):
    """[PHYSICS] 모터 제어 + 충돌 응답. 팔이 장애물에 막히거나 물건이 넘어지는 걸
    실제로 시뮬레이션한다. 블록을 그리퍼에 강제로 붙이지 않는다 — 물리가 결정."""
    mutated_sg, body_map, home_q, goals, err = _load_and_pose(
        scene_path, mutation_params, cid, robot_cfg)
    if err:
        return None, err

    robot_id = get_robot_id()
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    fingers = robot_cfg["robot"]["finger_joint_indices"]

    # 마찰 ↑ — 그리퍼가 물건을 마찰로 쥘 수 있게
    target_body = body_map.get(mutated_sg.target().id)
    if target_body is not None:
        p.changeDynamics(target_body, -1, lateralFriction=1.5, physicsClientId=cid)
    for f in fingers:
        p.changeDynamics(robot_id, f, lateralFriction=1.5, physicsClientId=cid)

    p.setTimeStep(1 / 240.0, physicsClientId=cid)
    ARM_FORCE, GRIP_FORCE = 180.0, 40.0

    # 객체가 테이블 위에 안정될 때까지 잠깐 정착
    for i, a in enumerate(home_q):
        p.resetJointState(robot_id, i, a, physicsClientId=cid)
    for _ in range(120):
        p.stepSimulation(physicsClientId=cid)

    frames = []
    steps_per_goal = 130
    capture_every = 8
    total_caps = len(goals) * (steps_per_goal // capture_every)
    cap = 0
    for q_goal, grip in goals:
        for i in range(n_arm):
            p.setJointMotorControl2(robot_id, i, p.POSITION_CONTROL,
                                    targetPosition=q_goal[i], force=ARM_FORCE,
                                    physicsClientId=cid)
        for f in fingers:
            p.setJointMotorControl2(robot_id, f, p.POSITION_CONTROL,
                                    targetPosition=grip, force=GRIP_FORCE,
                                    physicsClientId=cid)
        for s in range(steps_per_goal):
            p.stepSimulation(physicsClientId=cid)
            if s % capture_every == 0:
                yaw = 35 + 40 * (cap / max(total_caps - 1, 1))
                frames.append(capture_frame(cid, width, height, yaw))
                cap += 1
    return frames, None


def main():
    args = parse_args()
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    # 케이스 목록 구성
    if args.pass_scene:
        cases = [{
            "test_id": f"PASS_{args.pass_scene}",
            "verdict": "PASS", "failure_type": "-",
            "reason": "원본 씬, mutation 없음 — 정상 동작",
            "mutation_params": {},
        }]
        scene_id = args.pass_scene
    elif args.log:
        cases, scene_id = load_test_cases(args.log, args.test_index, args.verdict)
    else:
        print("❌ --log 또는 --pass-scene 중 하나가 필요합니다")
        return

    if not cases:
        print("❌ 일치하는 케이스 없음")
        return
    cases = cases[: args.max]

    os.makedirs(args.output_dir, exist_ok=True)
    base_scene_path = f"data/scene_library/{scene_id}.json"
    robot_cfg = load_robot_config("config/robot_config.yaml")

    cid = p.connect(p.DIRECT)
    import pybullet_data
    p.setAdditionalSearchPath(pybullet_data.getDataPath(), physicsClientId=cid)
    p.setGravity(0, 0, -9.81, physicsClientId=cid)
    scene_builder._client_id = cid          # 같은 클라이언트 강제 공유
    sim_runner._ROBOT_BODY_ID = None

    mode = "PHYSICS(동역학)" if args.physics else "KINEMATIC"
    suffix = "_physics" if args.physics else ""
    print(f"\n🎬 {len(cases)}개 케이스 애니메이션 생성  [모드: {mode}]\n")
    try:
        for i, rec in enumerate(cases, 1):
            tid = rec["test_id"]
            print(f"[{i}/{len(cases)}] {tid} [{rec['verdict']}] {rec['failure_type']}")
            print(f"    {rec['reason']}")
            if args.physics:
                frames, err = build_animation_physics(
                    base_scene_path, rec["mutation_params"], cid, robot_cfg,
                    args.width, args.height,
                )
            else:
                frames, err = build_animation(
                    base_scene_path, rec["mutation_params"], cid, robot_cfg,
                    args.width, args.height, args.samples,
                )
            if err:
                print(f"    ⚠️ {err}\n")
                continue
            uniq = len({f.tobytes() for f in frames})
            if uniq <= 1:
                print(f"    ❌ 모든 프레임 동일 (렌더 실패) — 저장 안 함\n")
                continue
            out = os.path.join(args.output_dir, f"{tid}{suffix}.gif")
            imageio.mimsave(out, frames, fps=args.fps, loop=0)
            print(f"    ✓ {len(frames)}프레임, {uniq}개 고유 → {out}\n")
    finally:
        p.disconnect(physicsClientId=cid)
    print("✓ 완료")


if __name__ == "__main__":
    main()
