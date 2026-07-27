"""types.py — LAM-Guided 파이프라인 공용 데이터클래스.

블루프린트 6.2~6.6의 RolloutTrace / BehaviorFeatures / VulnerabilityProfile /
GeneratedAsset / FailureCaseCandidate 를 MVP 범위로 구현한다.

모든 dataclass는 기존 관례대로 .to_dict() 를 제공한다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

import numpy as np

from scene_graph import ObjectNode

# ---------------------------------------------------------------------------
# Rollout: 정책이 무엇을 보고, 무엇을 골랐고, 어떻게 움직였는지
# ---------------------------------------------------------------------------

@dataclass
class RolloutTrace:
    case_id: str
    scene_id: str
    instruction: str
    expected_obj_id: str                 # ground-truth target id (sg.target().id)
    selected_obj_id: str                 # 실행 정책(VLA or IK)이 실제로 간 객체
    grasp_success: bool                  # 선택 객체에 대한 IK/VLA grasp 성공 여부
    ee_path: list[list[float]] = field(default_factory=list)
    reach_margin: float = 0.0
    path_min_obstacle_dist: float = 1.0
    target_clearance: float = 1.0
    human_zone_min_dist: float = 1.0
    destination_clearance: float = 1.0
    occlusion_ratio: float = 0.0
    stopped_for_safety: bool = False
    object_scores: dict[str, float] = field(default_factory=dict)
    kinematic: dict[str, Any] = field(default_factory=dict)  # KinematicResult 스냅샷
    # LAM+VLA 통합 모드 전용 필드
    lam_selected_obj_id: Optional[str] = None   # LAM이 고른 객체 (VLA 실행 전 판단)
    execution_mode: str = "lam_ik"              # "lam_ik" | "lam_vla"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 행동 취약성 feature
# ---------------------------------------------------------------------------

# to_vector() 순서 고정 (FEATURE_NAMES 관례와 동일하게 명시적 순서 유지)
BEHAVIOR_FEATURE_NAMES = [
    "wrong_object_selected",
    "selection_margin",
    "grasp_failed",
    "ee_oscillation",
    "human_zone_intrusion",
    "occlusion_level",
    "clearance_pressure",
    "reach_pressure",
]


@dataclass
class BehaviorFeatures:
    wrong_object_selected: float = 0.0   # 0/1
    selection_margin: float = 0.0        # score[selected] - score[expected] (작을수록 fragile)
    grasp_failed: float = 0.0            # 0/1
    ee_oscillation: float = 0.0          # 경로 방향 변화 누적
    human_zone_intrusion: float = 0.0    # max(0, safety_distance - human_zone_min_dist)
    occlusion_level: float = 0.0
    clearance_pressure: float = 0.0      # max(0, required_clearance - target_clearance)
    reach_pressure: float = 0.0          # max(0, -reach_margin)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_vector(self) -> np.ndarray:
        return np.array([getattr(self, n) for n in BEHAVIOR_FEATURE_NAMES], dtype=float)


# ---------------------------------------------------------------------------
# 취약성 프로파일 (LAM이 어떤 failure family에 약한지)
# ---------------------------------------------------------------------------

# 취약성 축 → failure family
VULNERABILITY_AXES = [
    "wrong_object_grounding",
    "occlusion_failure",
    "collision_risk",
    "insufficient_clearance",
    "safety_noncompliance",
    "recovery_failure",
    "action_instability",
]


@dataclass
class VulnerabilityProfile:
    scene_id: str
    scores: dict[str, float] = field(default_factory=dict)        # 축별 [0,1]
    recommended_families: list[str] = field(default_factory=list)  # 정렬된 family
    family_weights: dict[str, float] = field(default_factory=dict)  # 정규화된 family prior
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# 생성 asset 메타데이터
# ---------------------------------------------------------------------------

@dataclass
class GeneratedAsset:
    asset_id: str
    role: str                            # Role.DISTRACTOR | OBSTACLE | HUMAN_ZONE
    shape: str                           # "block" | "cylinder" | "mesh"
    size: list[float]                    # mesh면 AABB(=collision proxy & 시각 스케일 기준)
    semantic_tags: list[str] = field(default_factory=list)
    visual_similarity_to_target: float = 0.0  # 기준 target signature 대비 [0,1]
    family_affinity: list[str] = field(default_factory=list)
    mass: float = 0.1
    mesh_path: Optional[str] = None      # 생성된 메쉬(.obj) 경로. 있으면 shape="mesh"
    source: str = "procedural"           # procedural | shap_e | offline_mesh ...
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GeneratedAsset":
        return cls(
            asset_id=d["asset_id"], role=d["role"], shape=d["shape"],
            size=list(d["size"]), semantic_tags=list(d.get("semantic_tags", [])),
            visual_similarity_to_target=d.get("visual_similarity_to_target", 0.0),
            family_affinity=list(d.get("family_affinity", [])),
            mass=d.get("mass", 0.1), mesh_path=d.get("mesh_path"),
            source=d.get("source", "procedural"), extra=d.get("extra", {}),
        )

    def to_object_node(self, obj_id: str, position: list[float]) -> ObjectNode:
        """이 asset을 주어진 위치의 ObjectNode로 인스턴스화한다."""
        extra = dict(self.extra)
        extra.update({
            "semantic_tags": list(self.semantic_tags),
            "visual_similarity_to_target": self.visual_similarity_to_target,
            "asset_id": self.asset_id,
            "source": self.source,
        })
        shape = self.shape
        if self.mesh_path:               # 생성 메쉬 → mesh 분기로 스폰
            shape = "mesh"
            extra["mesh_path"] = self.mesh_path
        if self.role == "human_zone" and "radius" not in extra:
            extra["radius"] = max(self.size[0], self.size[1]) / 2
        return ObjectNode(
            id=obj_id,
            role=self.role,
            position=list(position),
            size=list(self.size),
            movable=(self.role != "human_zone"),
            shape=shape,
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Generator가 만드는 후보 테스트
# ---------------------------------------------------------------------------

@dataclass
class FailureCaseCandidate:
    case_id: str
    family: str                          # semantic_distractor | occluder | path_blocker | human_safety_intrusion
    base_scene_id: str
    instruction: str = ""
    insert_specs: list[dict[str, Any]] = field(default_factory=list)  # [{asset_id, position, role, obj_id, extra}]
    mutation_params: Optional[dict[str, float]] = None
    occlusion_ratio: float = 0.0
    expected_failure: str = ""           # 가설 (expected_failure_hypothesis)
    primary_param: dict[str, Any] = field(default_factory=dict)  # {"name":..., "value":...} for BoundaryRefiner
    acquisition_score: float = 0.0
    family_prior: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
