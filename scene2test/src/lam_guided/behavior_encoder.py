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
        wrong = 1.0 if (trace.selected_obj_id != trace.expected_obj_id
                        and trace.expected_obj_id) else 0.0

        # selection_margin = score[selected] - score[expected] (작을수록 fragile)
        ss = trace.object_scores
        if ss and trace.expected_obj_id in ss and trace.selected_obj_id in ss:
            sel_margin = ss[trace.selected_obj_id] - ss[trace.expected_obj_id]
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
