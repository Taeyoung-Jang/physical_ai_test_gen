"""sim_runner.py — Kinematic Motion Oracle.

동역학 grasp 없이 IK + 경로 보간 + 거리/충돌 쿼리만으로
robustness margin 계산에 필요한 기하학적 정보를 전부 수집한다.

주요 반환값:
  KinematicResult: IK 성공 여부, 경로 최소 거리, 도달 가능성 등
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pybullet as p
import pybullet_data
import yaml

from scene_builder import get_client

# ---------------------------------------------------------------------------
# 로봇 로드
# ---------------------------------------------------------------------------

_ROBOT_BODY_ID: Optional[int] = None


def load_robot(robot_cfg: dict) -> int:
    """Franka Panda URDF을 로드하고 body_id를 반환한다."""
    global _ROBOT_BODY_ID
    cid = get_client()
    urdf = robot_cfg["robot"]["urdf"]
    base_pos = robot_cfg["robot"]["base_position"]
    base_orn = p.getQuaternionFromEuler(robot_cfg["robot"]["base_orientation_rpy"])
    use_fixed = robot_cfg["robot"]["use_fixed_base"]

    _ROBOT_BODY_ID = p.loadURDF(
        urdf,
        basePosition=base_pos,
        baseOrientation=base_orn,
        useFixedBase=use_fixed,
        physicsClientId=cid,
    )

    # home 자세로 초기화
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    for i, q in enumerate(home_q[:n_arm]):
        p.resetJointState(_ROBOT_BODY_ID, i, q, physicsClientId=cid)

    return _ROBOT_BODY_ID


def get_robot_id() -> int:
    if _ROBOT_BODY_ID is None:
        raise RuntimeError("load_robot()를 먼저 호출하세요.")
    return _ROBOT_BODY_ID


# ---------------------------------------------------------------------------
# IK
# ---------------------------------------------------------------------------

def solve_ik(
    target_pos: list[float],
    target_orn: Optional[list[float]],
    robot_cfg: dict,
    max_iters: Optional[int] = None,
) -> Optional[list[float]]:
    """target_pos/orn에 대한 IK를 풀고 joint angle list를 반환한다.
    실패 시 None.
    """
    cid = get_client()
    robot_id = get_robot_id()
    ee_link = robot_cfg["robot"]["ee_link_index"]
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    iters = max_iters or robot_cfg["motion"]["ik_max_iters"]
    threshold = robot_cfg["motion"]["ik_residual_threshold"]

    orn = target_orn if target_orn is not None else p.getQuaternionFromEuler([0, math.pi, 0])

    joint_poses = p.calculateInverseKinematics(
        robot_id, ee_link,
        targetPosition=target_pos,
        targetOrientation=orn,
        maxNumIterations=iters,
        residualThreshold=threshold,
        physicsClientId=cid,
    )

    # 실제 도달 거리 검증
    for i, q in enumerate(joint_poses[:n_arm]):
        p.resetJointState(robot_id, i, q, physicsClientId=cid)

    ee_state = p.getLinkState(robot_id, ee_link, physicsClientId=cid)
    actual_pos = np.array(ee_state[4])
    residual = float(np.linalg.norm(actual_pos - np.array(target_pos)))

    if residual > threshold * 10:
        return None

    return list(joint_poses[:n_arm])


def get_ee_position(robot_cfg: dict) -> np.ndarray:
    cid = get_client()
    robot_id = get_robot_id()
    ee_link = robot_cfg["robot"]["ee_link_index"]
    state = p.getLinkState(robot_id, ee_link, physicsClientId=cid)
    return np.array(state[4])


# ---------------------------------------------------------------------------
# 경로 보간
# ---------------------------------------------------------------------------

def interpolate_joint_path(
    q_start: list[float],
    q_end: list[float],
    n_samples: int,
) -> list[list[float]]:
    """두 joint 구성 사이를 선형 보간한 waypoint 리스트를 반환한다."""
    q_s = np.array(q_start)
    q_e = np.array(q_end)
    return [
        (q_s + t * (q_e - q_s)).tolist()
        for t in np.linspace(0, 1, n_samples)
    ]


def set_joint_state(q: list[float], robot_cfg: dict) -> None:
    cid = get_client()
    robot_id = get_robot_id()
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    for i, angle in enumerate(q[:n_arm]):
        p.resetJointState(robot_id, i, angle, physicsClientId=cid)


# ---------------------------------------------------------------------------
# 충돌 / 거리 쿼리
# ---------------------------------------------------------------------------

def get_closest_distance(body_a: int, body_b: int, max_dist: float = 1.0) -> float:
    """두 body 사이의 최소 거리(m)를 반환한다. 겹치면 음수."""
    cid = get_client()
    contacts = p.getClosestPoints(body_a, body_b, max_dist, physicsClientId=cid)
    if not contacts:
        return max_dist
    return min(c[8] for c in contacts)


def check_path_clearances(
    waypoints: list[list[float]],
    obstacle_body_ids: list[int],
    robot_cfg: dict,
    robot_body_id: int,
) -> dict[str, float]:
    """경로 waypoint 전체를 순회하며 장애물별 최소 거리를 반환한다."""
    cid = get_client()
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    min_dists: dict[int, float] = {bid: 1.0 for bid in obstacle_body_ids}

    original_q = [
        p.getJointState(robot_body_id, i, physicsClientId=cid)[0]
        for i in range(n_arm)
    ]

    for q in waypoints:
        set_joint_state(q, robot_cfg)
        for obs_id in obstacle_body_ids:
            d = get_closest_distance(robot_body_id, obs_id)
            if d < min_dists[obs_id]:
                min_dists[obs_id] = d

    # 원래 자세 복원
    for i, angle in enumerate(original_q):
        p.resetJointState(robot_body_id, i, angle, physicsClientId=cid)

    return {str(bid): v for bid, v in min_dists.items()}


# ---------------------------------------------------------------------------
# 경로 포인트 (EE 위치 시퀀스)
# ---------------------------------------------------------------------------

def get_ee_path(
    waypoints_q: list[list[float]],
    robot_cfg: dict,
    robot_body_id: int,
) -> list[np.ndarray]:
    """joint waypoints에 대응하는 EE 위치 리스트를 반환한다."""
    cid = get_client()
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    ee_link = robot_cfg["robot"]["ee_link_index"]
    positions = []

    original_q = [
        p.getJointState(robot_body_id, i, physicsClientId=cid)[0]
        for i in range(n_arm)
    ]

    for q in waypoints_q:
        for i, angle in enumerate(q[:n_arm]):
            p.resetJointState(robot_body_id, i, angle, physicsClientId=cid)
        state = p.getLinkState(robot_body_id, ee_link, physicsClientId=cid)
        positions.append(np.array(state[4]))

    for i, angle in enumerate(original_q):
        p.resetJointState(robot_body_id, i, angle, physicsClientId=cid)

    return positions


# ---------------------------------------------------------------------------
# Kinematic Check 결과
# ---------------------------------------------------------------------------

@dataclass
class KinematicResult:
    """한 번의 kinematic oracle 실행 결과."""

    # IK
    ik_success: bool = False
    ik_residual: float = float("inf")     # m
    robot_to_target_distance: float = 0.0 # m
    reach_margin: float = 0.0             # max_reach - distance

    # 경로 충돌
    path_min_obstacle_dist: float = 1.0   # m, 경로 전체 최소 장애물 거리
    path_obstacle_body_ids: list[int] = field(default_factory=list)

    # clearance (target 주변)
    target_clearance: float = 1.0         # m, target 주변 최소 장애물 거리

    # EE path positions (m)
    ee_path: list[list[float]] = field(default_factory=list)

    # human zone 최소 거리 (경로 ↔ human_zone)
    human_zone_min_dist: float = 1.0      # m

    # destination (tray 여유)
    destination_clearance: float = 1.0    # m, tray 주변 최소 장애물 거리

    # perception
    occlusion_ratio: float = 0.0


# ---------------------------------------------------------------------------
# 메인 kinematic oracle 실행
# ---------------------------------------------------------------------------

def run_kinematic_check(
    target_pos: list[float],
    destination_pos: list[float],
    obstacle_body_ids: list[int],
    human_zone_body_ids: list[int],
    destination_body_id: int,
    robot_body_id: int,
    robot_cfg: dict,
    occlusion_ratio: float = 0.0,
) -> KinematicResult:
    """kinematic oracle 전체를 실행하고 KinematicResult를 반환한다."""
    cid = get_client()
    result = KinematicResult(occlusion_ratio=occlusion_ratio)

    max_reach = robot_cfg["robot"]["max_reach"]
    robot_base = np.array(robot_cfg["robot"]["base_position"])
    n_samples = robot_cfg["motion"]["path_samples_per_segment"]

    # 1) 로봇↔target 거리
    target_np = np.array(target_pos)
    result.robot_to_target_distance = float(np.linalg.norm(target_np - robot_base))
    result.reach_margin = max_reach - result.robot_to_target_distance

    # 2) IK (grasp pose: target 위에서 수직 하강)
    pre_grasp_pos = [target_pos[0], target_pos[1],
                     target_pos[2] + robot_cfg["motion"]["pre_offset"]]
    grasp_pos = list(target_pos)
    grasp_orn = p.getQuaternionFromEuler([0, math.pi, 0])

    q_pre = solve_ik(pre_grasp_pos, list(grasp_orn), robot_cfg)
    q_grasp = solve_ik(grasp_pos, list(grasp_orn), robot_cfg)

    if q_grasp is None:
        result.ik_success = False
        return result

    result.ik_success = True

    # 실제 IK 잔차
    ee_state = p.getLinkState(robot_body_id, robot_cfg["robot"]["ee_link_index"],
                               physicsClientId=cid)
    result.ik_residual = float(
        np.linalg.norm(np.array(ee_state[4]) - np.array(grasp_pos))
    )

    # 3) 경로 생성 (home → pre_grasp → grasp)
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4]
    n_arm = robot_cfg["robot"]["num_arm_joints"]
    home_q = home_q[:n_arm]
    q_pre = q_pre or home_q

    path_home_to_pre = interpolate_joint_path(home_q, q_pre, n_samples)
    path_pre_to_grasp = interpolate_joint_path(q_pre, q_grasp, n_samples)
    full_path = path_home_to_pre + path_pre_to_grasp

    # EE positions
    ee_positions = get_ee_path(full_path, robot_cfg, robot_body_id)
    result.ee_path = [pos.tolist() for pos in ee_positions]

    # 4) 경로 ↔ obstacle 최소 거리
    if obstacle_body_ids:
        dists = check_path_clearances(full_path, obstacle_body_ids, robot_cfg, robot_body_id)
        result.path_min_obstacle_dist = min(dists.values()) if dists else 1.0
        result.path_obstacle_body_ids = [
            int(bid) for bid, v in dists.items()
            if v == result.path_min_obstacle_dist
        ]

    # 5) target 주변 clearance (장애물과 target의 표면간 거리)
    target_body_ids = [
        bid for bid in _get_all_bodies(cid)
        if bid != robot_body_id and bid not in obstacle_body_ids
    ]
    # 간단히 obstacle ↔ target body 거리로 근사
    if obstacle_body_ids:
        # target이 body_map에 있으면 직접 쿼리, 없으면 위치 기반 근사
        clearances = []
        for obs_id in obstacle_body_ids:
            # target 위치와 obstacle 거리 (수평)
            obs_state = p.getBasePositionAndOrientation(obs_id, physicsClientId=cid)
            obs_pos = np.array(obs_state[0])
            horizontal_dist = float(
                np.linalg.norm(obs_pos[:2] - target_np[:2])
            )
            clearances.append(horizontal_dist)
        result.target_clearance = min(clearances) if clearances else 1.0

    # 6) human_zone ↔ EE path 최소 거리
    if human_zone_body_ids and ee_positions:
        min_human_dist = float("inf")
        for hz_id in human_zone_body_ids:
            hz_state = p.getBasePositionAndOrientation(hz_id, physicsClientId=cid)
            hz_pos = np.array(hz_state[0])
            for ee_pos in ee_positions:
                d = float(np.linalg.norm(ee_pos[:2] - hz_pos[:2]))
                if d < min_human_dist:
                    min_human_dist = d
        result.human_zone_min_dist = min_human_dist

    # 7) destination clearance
    if obstacle_body_ids:
        dest_pos_np = np.array(destination_pos)
        dest_clearances = []
        for obs_id in obstacle_body_ids:
            obs_state = p.getBasePositionAndOrientation(obs_id, physicsClientId=cid)
            obs_pos = np.array(obs_state[0])
            d = float(np.linalg.norm(obs_pos[:2] - dest_pos_np[:2]))
            dest_clearances.append(d)
        result.destination_clearance = min(dest_clearances) if dest_clearances else 1.0

    return result


def _get_all_bodies(cid: int) -> list[int]:
    return list(range(p.getNumBodies(physicsClientId=cid)))


# ---------------------------------------------------------------------------
# Config 로더 (편의 함수)
# ---------------------------------------------------------------------------

def load_robot_config(path: str = "config/robot_config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
