"""behavior_encoder.py — RolloutTrace → BehaviorFeatures.

블루프린트 7.5. rollout 을 그대로 쓰지 않고 행동 취약성 feature 로 변환한다.
"""
from __future__ import annotations

from lam_guided.policy_oracle import ee_oscillation
from lam_guided.types import BehaviorFeatures, RolloutTrace


class BehaviorTraceEncoder:
    def __init__(self, thresholds: dict):
        self.required_clearance = thresholds["clearance"]["required_gripper_clearance"]
        self.safety_distance = thresholds["safety"]["safety_distance"]

    def encode(self, trace: RolloutTrace) -> BehaviorFeatures:
        # lam_vla 모드: LAM 선택 기준으로 취약성을 측정 (VLA 실행 결과와 분리)
        lam_id = trace.lam_selected_obj_id or trace.selected_obj_id
        wrong = 1.0 if (lam_id != trace.expected_obj_id
                        and trace.expected_obj_id) else 0.0

        # selection_margin: LAM 점수 기준 (작을수록 fragile)
        ss = trace.object_scores
        if ss and trace.expected_obj_id in ss and lam_id in ss:
            sel_margin = ss[lam_id] - ss[trace.expected_obj_id]
        else:
            sel_margin = 0.0

        return BehaviorFeatures(
            wrong_object_selected=wrong,
            selection_margin=float(sel_margin),
            grasp_failed=0.0 if trace.grasp_success else 1.0,
            ee_oscillation=ee_oscillation(trace.ee_path),
            human_zone_intrusion=max(0.0, self.safety_distance - trace.human_zone_min_dist),
            occlusion_level=float(trace.occlusion_ratio),
            clearance_pressure=max(0.0, self.required_clearance - trace.target_clearance),
            reach_pressure=max(0.0, -trace.reach_margin),
        )
