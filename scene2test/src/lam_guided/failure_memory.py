"""failure_memory.py — counterexample 저장 + novelty/redundancy/coverage.

블루프린트 11. 발견된 counterexample 을 jsonl 로 저장하고, 다음 후보 점수화에
쓰일 novelty / redundancy / coverage 를 제공한다. (acquisition.py 의 수식 재현)
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

import numpy as np

from lam_guided.policy_oracle import PolicyOracleResult, PolicyVerdict
from lam_guided.types import BehaviorFeatures, FailureCaseCandidate, RolloutTrace

ALL_POLICY_FAILURES = {
    "wrong_object_grounding", "wrong_object_picked", "safety_noncompliance",
    "action_instability", "recovery_failure",
}


class FailureMemory:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self._records: list[dict[str, Any]] = []
        self._feature_vecs: list[np.ndarray] = []
        self.discovered_failures: set[str] = set()

    # ----------------------------------------------------------------- add
    def add(self, case: FailureCaseCandidate, result: PolicyOracleResult,
            trace: RolloutTrace, features: BehaviorFeatures,
            physical_failures: Optional[list[str]] = None,
            combined_verdict: Optional[str] = None) -> None:
        physical_failures = physical_failures or []
        all_types = list(result.failure_types) + physical_failures
        verdict = combined_verdict or result.verdict
        rec = {
            "counterexample_id": f"CE_{len(self._records):05d}",
            "case_id": case.case_id,
            "family": case.family,
            "verdict": verdict,
            "policy_verdict": result.verdict,
            "failure_types": all_types,
            "policy_failures": result.failure_types,
            "physical_failures": physical_failures,
            "primary_failure": result.primary_failure or (
                physical_failures[0] if physical_failures else ""),
            "instruction": case.instruction,
            "insert_specs": case.insert_specs,
            "primary_param": case.primary_param,
            "expected_obj_id": trace.expected_obj_id,
            "selected_obj_id": trace.selected_obj_id,
            "reach_margin": trace.reach_margin,
            "path_min_obstacle_dist": trace.path_min_obstacle_dist,
            "human_zone_min_dist": trace.human_zone_min_dist,
            "reason": result.reason,
        }
        self._records.append(rec)
        self._feature_vecs.append(features.to_vector())
        self.discovered_failures.update(all_types)
        if self.path:
            self._append_jsonl(rec)

    def _append_jsonl(self, rec: dict) -> None:
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # ----------------------------------------------------------------- scores
    def novelty(self, feat: BehaviorFeatures, k: int = 5) -> float:
        """기존 counterexample 과의 평균 k-NN 거리(정규화 전 raw). 멀수록 novel."""
        if not self._feature_vecs:
            return 1.0
        v = feat.to_vector()
        dists = [float(np.linalg.norm(v - fv)) for fv in self._feature_vecs]
        dists.sort()
        kk = dists[:k]
        return float(sum(kk) / len(kk))

    def redundancy(self, feat: BehaviorFeatures) -> float:
        """가장 가까운 counterexample 과 너무 가까우면 1 에 가까운 penalty."""
        if not self._feature_vecs:
            return 0.0
        v = feat.to_vector()
        min_d = min(float(np.linalg.norm(v - fv)) for fv in self._feature_vecs)
        return float(max(0.0, 1.0 - min_d / 0.05))

    def coverage_bonus(self, expected_failure: str) -> float:
        """아직 발견 못 한 failure type 을 유도하는 후보면 보너스."""
        hint_map = {
            "wrong_object_grounding": "wrong_object_grounding",
            "occlusion_failure": "wrong_object_grounding",   # occluder도 grounding 유도
            "collision_or_clearance_failure": "recovery_failure",
            "safety_noncompliance": "safety_noncompliance",
        }
        ft = hint_map.get(expected_failure)
        if ft and ft not in self.discovered_failures:
            return 1.0
        return 0.0

    # ----------------------------------------------------------------- query
    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def top_for_family(self, family: str) -> Optional[dict[str, Any]]:
        cands = [r for r in self._records if r["family"] == family
                 and r["verdict"] in (PolicyVerdict.FAIL, PolicyVerdict.BLOCKED)]
        return cands[0] if cands else None

    def __len__(self) -> int:
        return len(self._records)
