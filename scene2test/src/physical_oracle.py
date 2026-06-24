"""physical_oracle.py — 6종 Oracle + robustness score + 판정.

KinematicResult (sim_runner) 와 SceneGraph / thresholds 를 받아
각 margin을 계산하고 최종 판정 (PASS/FAIL/WARN/BLOCKED) 을 내린다.

판정 우선순위:
  safety_margin < 0  → BLOCKED  (human_risk, 무조건 최우선)
  robustness <= 0    → FAIL     (failure_type = binding margin 이름)
  0 < rob <= warn_band → WARN   (경계 조건)
  robustness > warn_band → PASS
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Optional

import yaml

from scene_graph import SceneGraph
from sim_runner import KinematicResult

# ---------------------------------------------------------------------------
# 판정값 상수
# ---------------------------------------------------------------------------

class Verdict:
    PASS    = "PASS"
    FAIL    = "FAIL"
    WARN    = "WARN"     # 경계 조건 (0 < robustness <= warn_band)
    BLOCKED = "BLOCKED"  # 안전 금지 (safety_margin < 0, 최우선)


# ---------------------------------------------------------------------------
# 임계값 로더
# ---------------------------------------------------------------------------

def load_thresholds(path: str = "config/thresholds.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# 개별 Margin 계산 (6종)
# ---------------------------------------------------------------------------

def _reach_margin(result: KinematicResult, robot_cfg: dict) -> float:
    """max_reach - robot_to_target_distance.
    IK 자체가 실패했으면 큰 음수를 반환한다.
    """
    if not result.ik_success:
        return -robot_cfg["robot"]["max_reach"]
    return result.reach_margin


def _clearance_margin(result: KinematicResult, thresholds: dict) -> float:
    """target 주변 여유 - 요구 clearance.
    target_clearance: 가장 가까운 obstacle ↔ target 수평 거리 (표면 간).
    """
    required = thresholds["clearance"]["required_gripper_clearance"]
    return result.target_clearance - required


def _collision_margin(result: KinematicResult, thresholds: dict) -> float:
    """경로 최소 obstacle 거리 - collision threshold."""
    threshold = thresholds["clearance"]["collision_threshold"]
    return result.path_min_obstacle_dist - threshold


def _safety_margin(result: KinematicResult, thresholds: dict) -> float:
    """경로 ↔ human_zone 최소 거리 - safety_distance."""
    required = thresholds["safety"]["safety_distance"]
    return result.human_zone_min_dist - required


def _goal_margin(result: KinematicResult, thresholds: dict) -> float:
    """destination 여유 - place_footprint_margin.
    destination_clearance: tray 주변 obstacle 거리.
    """
    required = thresholds["destination"]["place_footprint_margin"]
    return result.destination_clearance - required


def _perception_margin(result: KinematicResult, thresholds: dict) -> float:
    """perception confidence - threshold.
    occlusion_ratio가 클수록 perception_margin이 낮아진다.
    confidence = 1 - occlusion_ratio (단순 선형 근사)
    """
    block_ratio = thresholds["perception"]["occlusion_block_ratio"]
    confidence_threshold = thresholds["perception"]["confidence_threshold"]
    # occlusion_ratio가 block_ratio를 넘으면 confidence가 0으로 수렴
    confidence = max(0.0, 1.0 - result.occlusion_ratio / max(block_ratio, 1e-6))
    return confidence - confidence_threshold


# ---------------------------------------------------------------------------
# Oracle 결과
# ---------------------------------------------------------------------------

@dataclass
class OracleResult:
    test_id: str
    scene_id: str

    # 6개 margin (양수 = 여유 있음, 음수 = 위반)
    margins: dict[str, float] = field(default_factory=dict)

    # 최소 margin
    robustness: float = 0.0
    binding_margin: str = ""  # robustness를 결정한 margin 이름

    # 판정
    verdict: str = Verdict.PASS
    failure_type: str = ""
    reason: str = ""
    recommendation: str = ""

    # 원시 kinematic 데이터
    ik_success: bool = True
    robot_to_target_distance: float = 0.0
    path_min_obstacle_dist: float = 0.0


# ---------------------------------------------------------------------------
# 실패 유형 → 권고 문장 생성
# ---------------------------------------------------------------------------

_RECOMMENDATIONS: dict[str, str] = {
    "unreachable":              "target을 로봇 작업 반경(최대 {max_reach:.2f}m) 안쪽으로 이동하세요.",
    "insufficient_clearance":   "target 주변 장애물을 최소 {required_clearance:.0f}cm 이상 이동하세요.",
    "path_collision":           "로봇 경로 위의 장애물을 제거하거나 경로 외곽으로 이동하세요.",
    "human_risk":               "작업 경로에서 최소 {safety_dist:.0f}cm 이상 인원을 대피시키세요.",
    "destination_occupied":     "목적지(tray) 위 장애물을 제거하세요.",
    "perception_uncertainty":   "target 주변 occlusion을 제거하거나 카메라 각도를 조정하세요.",
}

_FAILURE_REASONS: dict[str, str] = {
    "unreachable":            "target이 로봇 작업 반경 밖에 있습니다 (reach_margin={margin:.3f}m).",
    "insufficient_clearance": "target 주변 여유 공간 {actual:.1f}cm < 요구 clearance {required:.1f}cm.",
    "path_collision":         "로봇 경로 위 장애물 최소 거리 {margin:.1f}cm < 충돌 임계값.",
    "human_risk":             "경로 ↔ 작업자 거리 {actual:.1f}cm < 안전 거리 {required:.1f}cm.",
    "destination_occupied":   "목적지 점유 — tray 위 장애물 거리 {margin:.1f}cm.",
    "perception_uncertainty": "target 주변 occlusion 비율 {ratio:.0%} > 임계값.",
}


def _make_reason(failure_type: str, margin: float, thresholds: dict, result: KinematicResult) -> str:
    if failure_type == "unreachable":
        return _FAILURE_REASONS["unreachable"].format(margin=margin)
    elif failure_type == "insufficient_clearance":
        req = thresholds["clearance"]["required_gripper_clearance"]
        actual = result.target_clearance * 100
        return _FAILURE_REASONS["insufficient_clearance"].format(
            actual=actual, required=req * 100)
    elif failure_type == "path_collision":
        return _FAILURE_REASONS["path_collision"].format(margin=margin * 100)
    elif failure_type == "human_risk":
        req = thresholds["safety"]["safety_distance"]
        actual = result.human_zone_min_dist * 100
        return _FAILURE_REASONS["human_risk"].format(actual=actual, required=req * 100)
    elif failure_type == "destination_occupied":
        return _FAILURE_REASONS["destination_occupied"].format(margin=margin * 100)
    elif failure_type == "perception_uncertainty":
        return _FAILURE_REASONS["perception_uncertainty"].format(ratio=result.occlusion_ratio)
    return ""


def _make_recommendation(failure_type: str, thresholds: dict, robot_cfg: dict) -> str:
    tmpl = _RECOMMENDATIONS.get(failure_type, "")
    return tmpl.format(
        max_reach=robot_cfg["robot"]["max_reach"],
        required_clearance=thresholds["clearance"]["required_gripper_clearance"] * 100,
        safety_dist=thresholds["safety"]["safety_distance"] * 100,
    )


# ---------------------------------------------------------------------------
# 메인 Oracle
# ---------------------------------------------------------------------------

# margin 이름 → failure_type 이름 매핑
_MARGIN_TO_FAILURE: dict[str, str] = {
    "reach":       "unreachable",
    "clearance":   "insufficient_clearance",
    "collision":   "path_collision",
    "safety":      "human_risk",
    "goal":        "destination_occupied",
    "perception":  "perception_uncertainty",
}


def evaluate(
    kinematic_result: KinematicResult,
    sg: SceneGraph,
    robot_cfg: dict,
    thresholds: dict,
    test_id: Optional[str] = None,
    mutation_params: Optional[dict] = None,
) -> OracleResult:
    """KinematicResult → OracleResult (margins + verdict + reason)."""

    tid = test_id or str(uuid.uuid4())[:8]
    res = OracleResult(test_id=tid, scene_id=sg.scene_id)
    res.ik_success = kinematic_result.ik_success
    res.robot_to_target_distance = kinematic_result.robot_to_target_distance
    res.path_min_obstacle_dist = kinematic_result.path_min_obstacle_dist

    # --- 6종 margin 계산 ---
    margins = {
        "reach":      _reach_margin(kinematic_result, robot_cfg),
        "clearance":  _clearance_margin(kinematic_result, thresholds),
        "collision":  _collision_margin(kinematic_result, thresholds),
        "safety":     _safety_margin(kinematic_result, thresholds),
        "goal":       _goal_margin(kinematic_result, thresholds),
        "perception": _perception_margin(kinematic_result, thresholds),
    }
    res.margins = {k: round(v, 5) for k, v in margins.items()}

    # --- robustness = min(margins) ---
    binding = min(margins, key=margins.get)
    rob = margins[binding]
    res.robustness = round(rob, 5)
    res.binding_margin = binding
    failure_type = _MARGIN_TO_FAILURE[binding]

    # --- 판정 (우선순위: BLOCKED > FAIL > WARN > PASS) ---
    warn_band = thresholds["decision"]["warn_band"]

    if margins["safety"] < 0:
        # safety 위반은 다른 margin과 관계없이 BLOCKED
        res.verdict = Verdict.BLOCKED
        res.failure_type = "human_risk"
        res.reason = _make_reason("human_risk", margins["safety"], thresholds, kinematic_result)
        res.recommendation = _make_recommendation("human_risk", thresholds, robot_cfg)
    elif rob <= 0:
        res.verdict = Verdict.FAIL
        res.failure_type = failure_type
        res.reason = _make_reason(failure_type, rob, thresholds, kinematic_result)
        res.recommendation = _make_recommendation(failure_type, thresholds, robot_cfg)
    elif rob <= warn_band:
        res.verdict = Verdict.WARN
        res.failure_type = failure_type  # 어느 margin이 아슬아슬한지
        res.reason = f"경계 조건 — {binding} margin={rob*100:.1f}cm (warn_band={warn_band*100:.0f}cm)"
        res.recommendation = _make_recommendation(failure_type, thresholds, robot_cfg)
    else:
        res.verdict = Verdict.PASS
        res.failure_type = ""
        res.reason = ""
        res.recommendation = ""

    return res


# ---------------------------------------------------------------------------
# 전체 실행 파이프라인 (scene_builder + sim_runner + oracle 통합)
# ---------------------------------------------------------------------------

def run_oracle_on_mutation(
    base_sg: SceneGraph,
    mutation_params: dict,
    robot_cfg: dict,
    thresholds: dict,
    test_id: Optional[str] = None,
) -> OracleResult:
    """base SceneGraph에 mutation을 적용하고 oracle까지 실행한다.

    scene_builder, sim_runner를 내부에서 호출한다.
    각 호출마다 PyBullet 장면을 리셋한다.
    """
    import scene_builder as sb
    import sim_runner as sr

    # 1. mutation 적용
    mutated_sg = sb.apply_mutation(base_sg, mutation_params)

    # 2. PyBullet 리셋 + 장면 로드
    sb.reset_simulation()
    body_map = sb.load_scene(mutated_sg)
    robot_id = sr.load_robot(robot_cfg)

    # 3. body_id 분류
    obstacle_ids = [body_map[o.id] for o in mutated_sg.obstacles() if o.id in body_map]
    hz_ids = [body_map[o.id] for o in mutated_sg.human_zones() if o.id in body_map]
    dest = mutated_sg.destination()
    dest_id = body_map.get(dest.id, -1) if dest else -1

    target = mutated_sg.target()
    t_pos = target.position if target else [0.5, 0.0, 0.05]
    d_pos = dest.position if dest else [0.6, 0.2, 0.03]

    occ_ratio = mutation_params.get("occlusion_ratio", 0.0)
    if mutated_sg.unknown_regions:
        occ_ratio = mutated_sg.unknown_regions[0].occlusion_ratio

    # 4. kinematic oracle
    kinematic = sr.run_kinematic_check(
        target_pos=t_pos,
        destination_pos=d_pos,
        obstacle_body_ids=obstacle_ids,
        human_zone_body_ids=hz_ids,
        destination_body_id=dest_id,
        robot_body_id=robot_id,
        robot_cfg=robot_cfg,
        occlusion_ratio=occ_ratio,
    )

    # 5. physical oracle
    return evaluate(kinematic, mutated_sg, robot_cfg, thresholds,
                    test_id=test_id, mutation_params=mutation_params)
