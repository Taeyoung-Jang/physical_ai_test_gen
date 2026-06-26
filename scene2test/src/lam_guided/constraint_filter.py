"""constraint_filter.py — 삽입 후보의 물리 유효성 필터.

블루프린트 9. generator 가 만든 후보를 삽입한 뒤, 삽입된 노드가 물리적으로
말이 되는지 검사한다. 기존 validity.py 의 기하 헬퍼를 재사용한다.

distractor 가 clearance zone 을 부분 침범하는 것은 허용(그게 목적)하되,
완전 관통이나 table 밖, robot base 충돌은 금지한다.
"""
from __future__ import annotations

import numpy as np

import validity as vd
from lam_guided.asset_bank import GeneratedAssetBank
from lam_guided.case_apply import insert_assets
from lam_guided.types import FailureCaseCandidate
from scene_graph import Role, SceneGraph


class ConstraintFilter:
    def __init__(self, robot_cfg: dict, overlap_margin: float = -0.01,
                 robot_base_clear: float = 0.12):
        # overlap_margin<0: 약간의 침범 허용 (clearance zone 자극 목적)
        self.robot_base = np.array(robot_cfg["robot"]["base_position"])
        self.overlap_margin = overlap_margin
        self.robot_base_clear = robot_base_clear

    def _bounds(self, sg: SceneGraph):
        if sg.support_surfaces:
            return sg.support_surfaces[0].bounds
        return {"x": [-10, 10], "y": [-10, 10]}

    def is_valid(self, sg: SceneGraph, case: FailureCaseCandidate,
                 asset_bank: GeneratedAssetBank) -> bool:
        try:
            out = insert_assets(sg, case.insert_specs, asset_bank)
        except KeyError:
            return False

        bounds = self._bounds(sg)
        inserted_ids = {s["obj_id"] for s in case.insert_specs}
        inserted = [o for o in out.objects if o.id in inserted_ids]

        for node in inserted:
            # human_zone 은 table 밖에 있어도 되고 충돌 shape 없음 → bounds/overlap 면제
            if node.role == Role.HUMAN_ZONE:
                # robot base 위에 사람을 세우진 않음
                if np.linalg.norm(np.array(node.position[:2]) - self.robot_base[:2]) < 0.1:
                    return False
                continue

            # table bounds 안
            if not vd.point_in_bounds(np.array(node.position), bounds, margin=0.0):
                return False
            # robot base 와 충돌 금지
            if np.linalg.norm(np.array(node.position[:2]) - self.robot_base[:2]) < self.robot_base_clear:
                return False
            # 기존 객체와 완전 관통 금지 (target/destination 포함). 약간 침범은 허용.
            for other in out.objects:
                if other.id == node.id or other.role == Role.HUMAN_ZONE:
                    continue
                ca, sa = np.array(node.position), np.array(node.size)
                cb, sb = np.array(other.position), np.array(other.size)
                if vd.aabb_overlap(ca, sa, cb, sb, margin=self.overlap_margin):
                    # 중심간 거리가 너무 가까우면(거의 동일 위치) 관통으로 간주
                    center_d = float(np.linalg.norm(ca[:2] - cb[:2]))
                    min_half = (min(sa[0], sa[1]) + min(sb[0], sb[1])) / 2
                    if center_d < 0.4 * min_half:
                        return False
        return True

    def filter(self, sg: SceneGraph, candidates: list[FailureCaseCandidate],
               asset_bank: GeneratedAssetBank) -> list[FailureCaseCandidate]:
        return [c for c in candidates if self.is_valid(sg, c, asset_bank)]
