"""boundary_refiner.py — 최소 perturbation 경계 탐색.

블루프린트 12. counterexample 을 하나 찾은 뒤, family 의 primary parameter 를
이분 탐색하여 PASS/FAIL 경계를 찾는다. 정책이 확률적(MiniActionModel 노이즈)이므로
각 parameter 값에서 여러 번 실행해 FAIL 율로 판정한다.

MVP 지원 family:
  semantic_distractor : distance_to_target (작을수록 FAIL)
  path_blocker        : offset_from_path   (작을수록 FAIL)
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Optional

import numpy as np

from lam_guided.asset_bank import GeneratedAssetBank, annotate_scene_semantics
from lam_guided.case_apply import apply_case
from lam_guided.policy_oracle import evaluate_physical_from_trace, evaluate_policy
from lam_guided.rollout import make_observation, run_policy_rollout
from lam_guided.types import FailureCaseCandidate
from scene_graph import SceneGraph


@dataclass
class BoundaryResult:
    family: str
    param_name: str
    fail_value: float          # 이 값 이하/근처에서 FAIL
    pass_value: float          # 이 값 이상/근처에서 PASS
    boundary: float            # 추정 경계
    iters: int = 0
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_REFINABLE = {
    "semantic_distractor": "distance_to_target",
    "path_blocker": "offset_from_path",
}


class BoundaryRefiner:
    def __init__(self, asset_bank: GeneratedAssetBank, action_model,
                 robot_cfg: dict, thresholds: dict, lam_cfg: dict):
        self.bank = asset_bank
        self.policy = action_model
        self.robot_cfg = robot_cfg
        self.thr = thresholds
        self.lam_cfg = lam_cfg
        self.robot_base = np.array(robot_cfg["robot"]["base_position"])
        bcfg = lam_cfg.get("boundary_refiner", {})
        self.max_iters = bcfg.get("max_iters", 8)
        self.tolerance = bcfg.get("tolerance", 0.005)
        self.samples = bcfg.get("samples_per_eval", 6)
        self.rs = {"base": list(self.robot_base),
                   "max_reach": robot_cfg["robot"]["max_reach"]}

    # ----------------------------------------------------- case 재구성
    def _build_case(self, base_sg: SceneGraph, ce: dict, value: float) -> FailureCaseCandidate:
        pp = ce["primary_param"]
        asset_id = pp["asset_id"]
        target = base_sg.target()
        family = ce["family"]
        obj_id = f"refine_{family[:4]}_obj"

        if family == "semantic_distractor":
            # robot→target 에 수직으로 배치하여 distance_to_robot 을 ~일정하게 유지
            # → distance_to_target(proximity) 효과만 경계에 반영(혼선 제거).
            a = self.robot_base[:2]
            b = np.array(target.position[:2])
            ab = b - a
            normal = np.array([-ab[1], ab[0]])
            normal = normal / (np.linalg.norm(normal) + 1e-9)
            side = 1.0 if pp.get("angle", 0.0) % (2 * math.pi) < math.pi else -1.0
            pt = b + side * value * normal
            pos = [float(pt[0]), float(pt[1]), self.bank.get(asset_id).size[2] / 2]
        elif family == "path_blocker":
            # target 으로부터 로봇 쪽으로 거리 value 만큼 (generator 와 동일 기하)
            a = self.robot_base[:2]
            b = np.array(target.position[:2])
            toward_robot = a - b
            toward_robot = toward_robot / (np.linalg.norm(toward_robot) + 1e-9)
            pt = b + value * toward_robot
            pos = [float(pt[0]), float(pt[1]), self.bank.get(asset_id).size[2] / 2]
        else:
            raise ValueError(f"refine 미지원 family: {family}")

        return FailureCaseCandidate(
            case_id=f"refine_{ce['case_id']}", family=family,
            base_scene_id=base_sg.scene_id, instruction=ce.get("instruction", ""),
            insert_specs=[{"asset_id": asset_id, "obj_id": obj_id, "position": pos}],
            occlusion_ratio=0.0, primary_param={**pp, "value": value},
        )

    # ----------------------------------------------------- FAIL 율
    def _fail_rate(self, base_sg: SceneGraph, ce: dict, value: float) -> float:
        """family 에 맞는 신호로 FAIL 율 측정.

        semantic_distractor → grounding(정책) 실패만 센다. distractor를 obstacle로
        둔 물리 충돌이 경계를 가리지 않게 하기 위함.
        path_blocker → 물리 실패만 센다.
        """
        family = ce["family"]
        case = self._build_case(base_sg, ce, value)
        scene = annotate_scene_semantics(apply_case(base_sg, case, self.bank))
        fails = 0
        for i in range(self.samples):
            if hasattr(self.policy, "rng"):
                self.policy.rng = np.random.default_rng(1000 + i)
            plan = self.policy.predict(case.instruction, make_observation(scene), self.rs)
            trace = run_policy_rollout(scene, plan, self.robot_cfg, case.case_id)
            if family == "semantic_distractor":
                res = evaluate_policy(trace, self.thr, self.lam_cfg)
                hit = "wrong_object_grounding" in res.failure_types
            else:  # path_blocker
                phys = evaluate_physical_from_trace(trace, self.thr)
                hit = phys.verdict == "FAIL"
            if hit:
                fails += 1
        return fails / max(1, self.samples)

    def refine(self, base_sg: SceneGraph, ce: dict) -> Optional[BoundaryResult]:
        family = ce["family"]
        if family not in _REFINABLE:
            return None
        pname = _REFINABLE[family]

        gcfg = self.lam_cfg.get("generator", {})
        lo = gcfg.get("min_separation", 0.04) if family == "semantic_distractor" else 0.0
        hi = gcfg.get("selection_radius", 0.12) * 2 if family == "semantic_distractor" else 0.12

        # lo=가까움(FAIL 기대), hi=멈(PASS 기대)
        fail_thresh = 0.5
        low, high = lo, hi
        iters = 0
        for _ in range(self.max_iters):
            iters += 1
            mid = (low + high) / 2.0
            fr = self._fail_rate(base_sg, ce, mid)
            if fr >= fail_thresh:
                low = mid          # 여전히 FAIL → 경계는 더 큰 값
            else:
                high = mid         # PASS → 경계는 더 작은 값
            if abs(high - low) <= self.tolerance:
                break

        boundary = (low + high) / 2.0
        return BoundaryResult(
            family=family, param_name=pname,
            fail_value=round(low, 4), pass_value=round(high, 4),
            boundary=round(boundary, 4), iters=iters,
            note=f"{pname} ≲ {low:.3f}m 에서 정책 실패율 ≥ {fail_thresh:.0%}",
        )
