"""vla_bridge.py — VLA closed-loop 실행을 로드된 3D scene 세션 위에서 돌린다.

lam_guided/closed_loop.py의 run_closed_loop_rollout()과 같은 스텝 루프
(RGB 렌더 → policy.act → IK → step)을 그대로 쓰지만, 그 함수처럼 매 호출마다
scene_builder.reset_simulation()+load_scene()으로 PyBullet을 통째로 재로드하지
않는다 — SceneSearchSession이 이미 로드해 둔 HM3D 정적 mesh + 로봇을 재사용하고,
mutation이 반영된 위치만 session.apply_mutation_world()로 teleport한다
(scene3d.failure_search가 kinematic oracle 경로에서 이미 쓰는 것과 동일한 원칙 —
청크 200개+ 씬을 rollout마다 재로드하면 테스트 1건에 10초+ 걸려 탐색이 안 된다).

반환하는 RolloutTrace는 lam_guided.closed_loop과 완전히 동일한 스키마이므로
lam_guided.policy_oracle의 evaluate_policy/evaluate_physical_from_trace를
그대로 재사용할 수 있다 — 새 oracle을 만들지 않는다.
"""
from __future__ import annotations

import copy
import math

import numpy as np
import pybullet as p

from lam_guided.closed_loop import _target_clearance, infer_selected_object
from lam_guided.types import RolloutTrace
from policies_vla import ClosedLoopPolicy
from scene_graph import SceneGraph
from sim_runner import get_closest_distance, set_joint_state, solve_ik

from .failure_search import SceneSearchSession

POS_SCALE = 0.04           # m, 정규화 델타 1단위당 EE 이동량 (closed_loop.py와 동일)
OPEN, CLOSED = 0.04, 0.005


def render_workspace_rgb(
    session: SceneSearchSession, width: int = 224, height: int = 224,
) -> np.ndarray:
    """closed_loop.render_rgb와 동일 화각이지만 이 세션의 월드 좌표로 옮긴 카메라.

    Track A의 canonical 로컬 카메라(작업공간 정면, cam_target=[0.5,0,0.1],
    yaw=90, pitch=-30, distance=0.95)를 session.frame.to_world()로 월드
    좌표로 옮기고, yaw에 frame.theta(축정렬 회전각)를 더해 로컬 프레임 회전을
    보정한다 — session.frame이 "로봇 베이스=원점, 작업 방향=+x"가 되도록 만든
    바로 그 회전이므로, 카메라도 같은 만큼 돌리면 로봇 기준 상대 화각이
    session마다 동일하게 유지된다.
    """
    frame = session.frame
    cam_target_world = frame.to_world([0.5, 0.0, 0.1])
    world_yaw = 90.0 + math.degrees(frame.theta)
    view = p.computeViewMatrixFromYawPitchRoll(
        cameraTargetPosition=cam_target_world, distance=0.95,
        yaw=world_yaw, pitch=-30, roll=0, upAxisIndex=2,
        physicsClientId=session.cid,
    )
    proj = p.computeProjectionMatrixFOV(
        fov=58, aspect=width / height, nearVal=0.01, farVal=10.0,
        physicsClientId=session.cid,
    )
    _, _, rgba, _, _ = p.getCameraImage(
        width, height, viewMatrix=view, projectionMatrix=proj,
        renderer=p.ER_TINY_RENDERER, physicsClientId=session.cid,
    )
    return np.array(rgba, dtype=np.uint8).reshape(height, width, 4)[:, :, :3].copy()


def _to_world_scene_graph(local_sg: SceneGraph, frame) -> SceneGraph:
    """local_sg(로봇-로컬 프레임 좌표)를 월드 좌표로 변환한 사본.

    apply_mutation_world()가 실제로 body를 teleport하는 좌표와 정확히 같은
    변환이라 infer_selected_object/_target_clearance가 실제 body 위치와
    일치하는 SceneGraph를 보게 된다.
    """
    out = copy.deepcopy(local_sg)
    for obj in out.objects:
        obj.position = frame.to_world(obj.position)
        obj.size = frame.size_to_local(obj.size)  # 축정렬 회전이라 자기역함수
    return out


def _set_gripper(session: SceneSearchSession, robot_cfg: dict, width: float) -> None:
    for idx in robot_cfg["robot"]["finger_joint_indices"]:
        p.resetJointState(
            session.ws.robot_body_id, idx, width, physicsClientId=session.cid
        )


def run_closed_loop_on_session(
    session: SceneSearchSession,
    policy: ClosedLoopPolicy,
    mutated_local_sg: SceneGraph,
    instruction: str,
    case_id: str,
    max_steps: int = 40,
) -> RolloutTrace:
    """lam_guided.closed_loop.run_closed_loop_rollout과 동일한 스텝 루프를,
    이미 로드된 session 위에서(재로드 없이) 실행한다.

    mutated_local_sg: scene_builder.apply_mutation(session.local_sg, params)의
    결과 — session.apply_mutation_world()가 받는 것과 동일한 로컬 프레임
    SceneGraph.
    """
    cid = session.cid
    ws = session.ws
    frame = session.frame
    robot_cfg = ws.robot_cfg  # 월드 base_position 반영된 config (oracle 경로와 동일)

    world = session.apply_mutation_world(mutated_local_sg)
    world_sg = _to_world_scene_graph(mutated_local_sg, frame)
    # policy.reset()에는 로컬 프레임 그대로 넘긴다 — StubReachPolicy(MiniActionModel
    # 재사용)는 "로봇 베이스=원점"을 전제하는 Track A 관례를 그대로 쓴다(lam_guided
    # 쪽 코드는 건드리지 않음). 실제 OpenVLA는 robot_state를 아예 안 쓰므로 이 경로는
    # 스텁 검증에서만 의미가 있다.
    policy.reset(mutated_local_sg, instruction)

    n_arm = robot_cfg["robot"]["num_arm_joints"]
    ee_link = robot_cfg["robot"]["ee_link_index"]
    base = np.array(robot_cfg["robot"]["base_position"])
    max_reach = robot_cfg["robot"]["max_reach"]
    down = list(p.getQuaternionFromEuler([0, math.pi, 0], physicsClientId=cid))
    home_q = [0, -math.pi / 4, 0, -3 * math.pi / 4, 0, math.pi / 2, math.pi / 4][:n_arm]
    set_joint_state(home_q, robot_cfg)
    _set_gripper(session, robot_cfg, OPEN)

    obstacle_ids = world["obstacle_ids"]
    hz_ids = world["hz_ids"]
    hz_pos = [np.array(o.position[:2]) for o in world_sg.human_zones()]
    occ = world["occ_ratio"]

    ee_path: list[list[float]] = []
    min_obstacle = 1.0
    min_human = 1.0
    grasped = False
    # policy 쪽에는 항상 로컬 프레임(베이스=원점) 좌표를 준다 — Track A 관례 유지.
    rs = {"base": [0.0, 0.0, 0.0], "max_reach": max_reach}

    for _ in range(max_steps):
        ee_pos = list(p.getLinkState(ws.robot_body_id, ee_link, physicsClientId=cid)[4])
        rgb = render_workspace_rgb(session)
        rs["ee_pos"] = frame.to_local(ee_pos)
        a = np.asarray(policy.act(rgb, instruction, rs), dtype=float).reshape(-1)

        # a[0:3]는 policy 관점(로컬 프레임)의 이동 방향 — 월드로 회전시켜 적용.
        delta_world_xy = frame._rot @ np.array(a[0:2])
        target = [ee_pos[0] + POS_SCALE * float(delta_world_xy[0]),
                  ee_pos[1] + POS_SCALE * float(delta_world_xy[1]),
                  max(0.02, ee_pos[2] + POS_SCALE * a[2])]
        q = solve_ik(target, down, robot_cfg)
        if q is not None:
            set_joint_state(q, robot_cfg)
        grip = CLOSED if a[6] > 0.5 else OPEN
        _set_gripper(session, robot_cfg, grip)
        p.stepSimulation(physicsClientId=cid)

        ee_pos = list(p.getLinkState(ws.robot_body_id, ee_link, physicsClientId=cid)[4])
        ee_path.append(ee_pos)
        for oid in obstacle_ids:
            min_obstacle = min(min_obstacle, get_closest_distance(ws.robot_body_id, oid))
        for hp in hz_pos:
            min_human = min(min_human, float(np.linalg.norm(np.array(ee_pos[:2]) - hp)))

        if grip == CLOSED:
            sel = infer_selected_object(world_sg, np.array(ee_pos), radius=0.06)
            if sel is not None:
                grasped = True
                break

    final_ee = np.array(ee_path[-1]) if ee_path else base
    selected_id = infer_selected_object(world_sg, final_ee) or ""
    target_node = world_sg.target()
    expected_id = target_node.id if target_node is not None else ""
    sel_obj = world_sg.get_object(selected_id) if selected_id else None
    reach_ref = sel_obj if sel_obj is not None else target_node
    reach_margin = (
        max_reach - float(np.linalg.norm(np.array(reach_ref.position) - base))
        if reach_ref is not None else -max_reach
    )

    return RolloutTrace(
        case_id=case_id, scene_id=world_sg.scene_id, instruction=instruction,
        expected_obj_id=expected_id, selected_obj_id=selected_id,
        grasp_success=grasped,
        ee_path=[list(pt) for pt in ee_path],
        reach_margin=reach_margin,
        path_min_obstacle_dist=min_obstacle,
        target_clearance=_target_clearance(world_sg, selected_id) if selected_id else 1.0,
        human_zone_min_dist=min_human if hz_ids else 1.0,
        destination_clearance=1.0,
        occlusion_ratio=occ,
        stopped_for_safety=False,
        object_scores={},
        kinematic={"closed_loop": True, "steps": len(ee_path), "grasped": grasped},
        execution_mode="lam_vla",
    )
