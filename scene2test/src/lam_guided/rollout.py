"""rollout.py — 정책이 고른 객체를 실제로 실행해 RolloutTrace 를 만든다.

핵심: sim_runner.run_kinematic_check 는 target_pos 를 좌표 인자로 받으므로,
정책이 고른 객체의 position 을 넘기면 그 객체로 향하는 IK + 경로가 그대로 생성된다.
즉 wrong object 선택 시 실제로 다른 ee_path / margin 이 나온다(블루프린트 핵심).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

import scene_builder as sb
import sim_runner as sr
from lam_guided.types import RolloutTrace
from policies import ActionPlan
from scene_graph import Role, SceneGraph


def _robot_state(robot_cfg: dict) -> dict[str, Any]:
    return {
        "base": list(robot_cfg["robot"]["base_position"]),
        "max_reach": robot_cfg["robot"]["max_reach"],
    }


def make_observation(scene_sg: SceneGraph) -> SceneGraph:
    """정책에 주는 observation. MVP에서는 SceneGraph 자체가 observation."""
    return scene_sg


def run_policy_rollout(scene_sg: SceneGraph, plan: ActionPlan,
                       robot_cfg: dict, case_id: str) -> RolloutTrace:
    """선택된 객체로 kinematic rollout 실행 → RolloutTrace.

    호출 전 scene_sg 는 이미 case 적용(asset 삽입 등)이 끝난 상태여야 한다.
    """
    sb.reset_simulation()
    body_map = sb.load_scene(scene_sg)
    robot_id = sr.load_robot(robot_cfg)

    selected = scene_sg.get_object(plan.selected_obj_id)
    target = scene_sg.target()
    dest = scene_sg.destination()
    if selected is None:
        selected = target  # fallback

    # 장애물: 기존 obstacle + 선택되지 않은 distractor (잘못 뻗으면 clearance에도 영향)
    obstacle_ids = [body_map[o.id] for o in scene_sg.obstacles() if o.id in body_map]
    distractor_ids = [body_map[o.id] for o in scene_sg.by_role(Role.DISTRACTOR)
                      if o.id in body_map and o.id != plan.selected_obj_id]
    hz_ids = [body_map[o.id] for o in scene_sg.human_zones() if o.id in body_map]
    occ = scene_sg.unknown_regions[0].occlusion_ratio if scene_sg.unknown_regions else 0.0

    dest_pos = list(dest.position) if dest is not None else [0.6, 0.2, 0.03]
    dest_body = body_map.get(dest.id, -1) if dest is not None else -1

    kin = sr.run_kinematic_check(
        target_pos=list(selected.position),
        destination_pos=dest_pos,
        obstacle_body_ids=obstacle_ids + distractor_ids,
        human_zone_body_ids=hz_ids,
        destination_body_id=dest_body,
        robot_body_id=robot_id,
        robot_cfg=robot_cfg,
        occlusion_ratio=occ,
    )

    return RolloutTrace(
        case_id=case_id,
        scene_id=scene_sg.scene_id,
        instruction=plan.instruction,
        expected_obj_id=plan.expected_obj_id or (target.id if target else ""),
        selected_obj_id=plan.selected_obj_id,
        grasp_success=kin.ik_success,
        ee_path=[list(p) for p in kin.ee_path],
        reach_margin=kin.reach_margin,
        path_min_obstacle_dist=kin.path_min_obstacle_dist,
        target_clearance=kin.target_clearance,
        human_zone_min_dist=kin.human_zone_min_dist,
        destination_clearance=kin.destination_clearance,
        occlusion_ratio=occ,
        stopped_for_safety=plan.stopped_for_safety,
        object_scores=dict(plan.object_scores),
        kinematic=asdict(kin),
    )
