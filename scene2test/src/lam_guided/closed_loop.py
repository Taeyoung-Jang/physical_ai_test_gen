"""closed_loop.py — VLA(closed-loop) 정책용 rollout.

기존 rollout.run_policy_rollout 은 정책이 고른 객체로 IK 한 번에 도달하는 open-loop 방식.
여기서는 매 스텝 [RGB 렌더 → policy.act → 7-DoF EE 델타 → IK → step] 의 closed-loop 으로
로봇을 구동하고, 끝나면 실제로 어떤 객체로 갔는지(post-hoc)를 추정해 RolloutTrace 를 만든다.

산출 RolloutTrace 는 기존과 동일 스키마라 PolicyOracle/physical 체크가 그대로 동작한다.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pybullet as p

import scene_builder as sb
from lam_guided.types import RolloutTrace
from scene_graph import Role, SceneGraph
from sim_runner import (
    get_client,
    get_closest_distance,
    get_robot_id,
    load_robot,
    set_joint_state,
    solve_ik,
)

POS_SCALE = 0.04           # m, 정규화 델타 1단위당 EE 이동량
OPEN, CLOSED = 0.04, 0.005
_MANIP_ROLES = (Role.TARGET, Role.OBSTACLE, Role.DISTRACTOR)


def render_rgb(cid: int, width: int = 224, height: int = 224,
               cam_target=(0.5, 0.0, 0.1), distance: float = 0.95,
               yaw: float = 90.0, pitch: float = -30.0) -> np.ndarray:
    """작업공간 정면 RGB (VLA 입력). TinyRenderer (macOS 안전)."""
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=list(cam_target), distance=distance, yaw=yaw,
        pitch=pitch, roll=0, upAxisIndex=2, physicsClientId=cid)
    proj = p.computeProjectionMatrixFOV(
        fov=58, aspect=width / height, nearVal=0.01, farVal=10.0, physicsClientId=cid)
    _, _, rgba, _, _ = p.getCameraImage(
        width, height, viewMatrix=view, projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER, physicsClientId=cid)
    return np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()


def _set_gripper(robot_cfg, cid, width):
    rid = get_robot_id()
    for idx in robot_cfg["robot"]["finger_joint_indices"]:
        p.resetJointState(rid, idx, width, physicsClientId=cid)


def infer_selected_object(sg: SceneGraph, ee_xy: np.ndarray,
                          radius: float = 0.12) -> Optional[str]:
    """EE 최종 위치에 가장 가까운 조작 가능 객체(post-hoc 선택 추정)."""
    best_id, best_d = None, radius
    for o in sg.objects:
        if o.role not in _MANIP_ROLES:
            continue
        d = float(np.linalg.norm(np.array(o.position[:2]) - ee_xy[:2]))
        if d < best_d:
            best_id, best_d = o.id, d
    return best_id


def _target_clearance(sg: SceneGraph, obj_id: str) -> float:
    """선택 객체와 가장 가까운 다른 장애물 사이 표면 간 거리(근사)."""
    obj = sg.get_object(obj_id)
    if obj is None:
        return 1.0
    oc = np.array(obj.position[:2]); oh = min(obj.size[0], obj.size[1]) / 2
    best = 1.0
    for other in sg.objects:
        if other.id == obj_id or other.role in (Role.DESTINATION, Role.HUMAN_ZONE):
            continue
        d = float(np.linalg.norm(np.array(other.position[:2]) - oc))
        gap = d - oh - min(other.size[0], other.size[1]) / 2
        best = min(best, gap)
    return best


def run_closed_loop_rollout(scene_sg: SceneGraph, policy, robot_cfg: dict,
                            instruction: str, case_id: str,
                            max_steps: int = 40,
                            collect_frames: bool = False) -> RolloutTrace:
    """closed-loop 으로 정책을 구동하고 RolloutTrace 를 만든다.

    policy: ClosedLoopPolicy (reset/act). 호출 전 scene_sg 는 case 적용이 끝난 상태.
    """
    cid = get_client()
    sb.reset_simulation()
    body_map = sb.load_scene(scene_sg)
    robot_id = load_robot(robot_cfg)
    policy.reset(scene_sg, instruction)

    n_arm = robot_cfg["robot"]["num_arm_joints"]
    ee_link = robot_cfg["robot"]["ee_link_index"]
    base = np.array(robot_cfg["robot"]["base_position"])
    max_reach = robot_cfg["robot"]["max_reach"]
    down = list(p.getQuaternionFromEuler([0, math.pi, 0], physicsClientId=cid))
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4][:n_arm]
    set_joint_state(home_q, robot_cfg)
    _set_gripper(robot_cfg, cid, OPEN)

    obstacle_ids = [body_map[o.id] for o in scene_sg.obstacles() if o.id in body_map]
    distractor_ids = [body_map[o.id] for o in scene_sg.by_role(Role.DISTRACTOR)
                      if o.id in body_map]
    hz_pos = [np.array(o.position[:2]) for o in scene_sg.human_zones()]
    occ = scene_sg.unknown_regions[0].occlusion_ratio if scene_sg.unknown_regions else 0.0

    ee_path: list[list[float]] = []
    min_obstacle = 1.0
    min_human = 1.0
    grasped = False
    rs = {"base": list(base), "max_reach": max_reach}
    frames = []

    for _ in range(max_steps):
        ee_pos = list(p.getLinkState(robot_id, ee_link, physicsClientId=cid)[4])
        rgb = render_rgb(cid)
        if collect_frames:
            frames.append(rgb)
        rs["ee_pos"] = ee_pos
        a = np.asarray(policy.act(rgb, instruction, rs), dtype=float).reshape(-1)

        target = [ee_pos[0] + POS_SCALE * a[0],
                  ee_pos[1] + POS_SCALE * a[1],
                  max(0.02, ee_pos[2] + POS_SCALE * a[2])]
        q = solve_ik(target, down, robot_cfg)
        if q is not None:
            set_joint_state(q, robot_cfg)
        grip = CLOSED if a[6] > 0.5 else OPEN
        _set_gripper(robot_cfg, cid, grip)
        p.stepSimulation(physicsClientId=cid)

        ee_pos = list(p.getLinkState(robot_id, ee_link, physicsClientId=cid)[4])
        ee_path.append(ee_pos)
        for oid in obstacle_ids + distractor_ids:
            min_obstacle = min(min_obstacle, get_closest_distance(robot_id, oid))
        for hp in hz_pos:
            min_human = min(min_human, float(np.linalg.norm(np.array(ee_pos[:2]) - hp)))

        # grasp 판정: 그리퍼 닫힘 + 조작객체 근처
        if grip == CLOSED:
            sel = infer_selected_object(scene_sg, np.array(ee_pos), radius=0.06)
            if sel is not None:
                grasped = True
                break

    final_ee = np.array(ee_path[-1]) if ee_path else np.array([0, 0, 0])
    selected_id = infer_selected_object(scene_sg, final_ee) or ""
    target = scene_sg.target()
    expected_id = target.id if target is not None else ""
    sel_obj = scene_sg.get_object(selected_id) if selected_id else None
    reach_ref = sel_obj if sel_obj is not None else target
    reach_margin = (max_reach - float(np.linalg.norm(np.array(reach_ref.position) - base))
                    if reach_ref is not None else -max_reach)

    trace = RolloutTrace(
        case_id=case_id, scene_id=scene_sg.scene_id, instruction=instruction,
        expected_obj_id=expected_id, selected_obj_id=selected_id,
        grasp_success=grasped,
        ee_path=[list(p_) for p_ in ee_path],
        reach_margin=reach_margin,
        path_min_obstacle_dist=min_obstacle,
        target_clearance=_target_clearance(scene_sg, selected_id) if selected_id else 1.0,
        human_zone_min_dist=min_human,
        destination_clearance=1.0,
        occlusion_ratio=occ,
        stopped_for_safety=False,
        object_scores={},                      # closed-loop: per-object 점수 없음
        kinematic={"closed_loop": True, "steps": len(ee_path), "grasped": grasped},
    )
    if collect_frames:
        trace.kinematic["frames"] = len(frames)
        return trace, frames
    return trace
